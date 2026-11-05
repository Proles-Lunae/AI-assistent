"""Run the assistant: wait for a double clap, then greet you with the temperature."""

from __future__ import annotations

import argparse
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from .brain import BrainError, ClaudeBrain
from .config import Config, ConfigError, load_config
from .listening import (MicrophoneStopped, Transcriber, drain, record_question,
                        sounds_unfinished)
from .microphone import choose_microphone, list_devices, listen, recording, show_levels
from .phrases import all_goodbye_words, phrases_for
from .timeframes import GREETINGS, frame_end, frame_start, time_of_day
from .voice import Speaker, Speech
from .weather import detect_location, find_city, get_weather

WEATHER_WAIT = 15.0  # seconds; after this, give up on the weather for this clap
MAX_CONTINUATIONS = 3  # how many times she waits for the rest of an unfinished question


class Assistant:
    """She waits for claps, greets you, and talks with you.

    ``events(kind, **data)`` is told what's happening, for the window:
    "state" (state = starting, waiting, listening, thinking or speaking),
    "said" (text she says), "heard" (text you said), "weather" (temperature,
    unit, city), "level" (microphone loudness), "clap", "note" (text).
    """

    def __init__(self, config: Config, events=None):
        self.config = config
        self.events = events or (lambda kind, **data: None)
        self.words = phrases_for(config.user.language)  # everything she says, in her language
        self.speaker = Speaker(config.voice, self.words.code, self.words.voice)
        self.speaker.on_speak = self._speaking
        self._ready: dict[str, Speech] = {}  # greetings and the no-weather line, by text
        self._pool = ThreadPoolExecutor(max_workers=2)
        self.brain = ClaudeBrain(config.brain)
        self.transcriber = Transcriber(config.listen, self.words.code, self.words.whisper_prompt)

    def _speaking(self, text: str, continued: bool = False) -> None:
        self.events("state", state="speaking")
        self.events("said", text=text, continued=continued)

    def note(self, text: str) -> None:
        """A message worth showing: printed, and shown in the window."""
        print(f"({text})")
        self.events("note", text=text)

    def recording(self, text: str) -> Speech:
        """The recording of a fixed sentence, made once and then reused."""
        if text not in self._ready:
            self._ready[text] = self.speaker.prepare(text)
        return self._ready[text]

    def weather_speech(self, now: datetime) -> Speech:
        """Check the temperature (and rain chance) right now and record the sentence."""
        start = frame_start(now)
        settings = self.config.weather
        try:
            weather = get_weather(settings.city, settings.units, start, frame_end(start))
        except Exception as exc:
            self.note(f"Couldn't get the weather: {exc}")
            return self.recording(self.words.no_weather)
        self.events("weather", temperature=round(weather.temperature),
                    unit=weather.temperature_unit, city=weather.city)
        return self.speaker.prepare(weather.spoken(time_of_day(now), self.words.code))

    def wake_up(self) -> None:
        """Greet at once; the weather is checked fresh while the greeting plays."""
        now = datetime.now()
        weather = self._pool.submit(self.weather_speech, now)
        greeting = self.words.greeting(time_of_day(now), self.config.user.address())
        self.speaker.play(self.recording(greeting), wait=False)
        try:
            speech = weather.result(timeout=WEATHER_WAIT)
        except Exception as exc:
            print(f"(The weather took too long: {exc})")
            speech = self.recording(self.words.no_weather)
        self.speaker.finish()  # let the greeting end, then carry straight on
        self.speaker.play(speech)

    def converse(self, blocks) -> None:
        """Listen for questions and answer them, until you tell her to stop."""
        rate = self.config.clap.sample_rate
        settings = self.config.listen
        history: list[tuple[str, str]] = []
        ready_beep = True  # beep when she starts listening, and after each answer
        quiet_for = 0.0
        while True:
            if ready_beep:
                self.speaker.beep()
                self.events("state", state="listening")
                drain(blocks)  # forget what the microphone heard while she was talking
                print('Listening to you... (say "stop" or "goodbye" when you\'re done)')
                ready_beep, quiet_for = False, 0.0
            try:
                audio = record_question(blocks, rate, settings, on_level=self._level)
            except MicrophoneStopped as exc:
                print(f"(Stopped listening: {exc})")
                return
            if audio is None:  # nothing said yet: keep waiting quietly
                quiet_for += settings.wait_seconds
                if settings.end_after_quiet and quiet_for >= settings.end_after_quiet:
                    print("(Quiet for a while; back to waiting for claps.)")
                    return
                continue
            self.events("state", state="thinking")
            try:
                question = self.hear_out(blocks, audio)
            except MicrophoneStopped as exc:
                print(f"(Stopped listening: {exc})")
                return
            except Exception as exc:  # e.g. faster-whisper not installed
                print(f"(Couldn't turn your speech into text: {exc})")
                return
            ready_beep = True
            if not question:
                self.speaker.play(self.recording(self.words.didnt_catch))
                continue
            print(f"You: {question}")
            self.events("heard", text=question)
            if is_goodbye(question):
                self.speaker.play(self.recording(self.words.goodbye))
                return
            print("(Thinking...)")
            try:
                # She starts speaking as soon as Claude has written the first
                # sentence, and says the rest while it's still being written.
                answer = self.speaker.say_sentences(self.brain.answer_in_sentences(
                    question, history, self.context(), self.config.user.address(),
                    self.words.claude_instruction))
            except BrainError as exc:
                self.note(f"Claude couldn't answer: {exc}")
                self.speaker.play(self.recording(self.words.no_brain))
                continue  # she can still be asked again, or told to stop
            history.append((question, answer))

    def hear_out(self, blocks, audio) -> str:
        """Turn your question into text, waiting a little longer while it sounds
        unfinished, so she doesn't answer while you're still speaking."""
        import numpy as np

        rate, settings = self.config.clap.sample_rate, self.config.listen
        question = self.transcriber.transcribe(audio, rate)
        for _ in range(MAX_CONTINUATIONS):
            if not sounds_unfinished(question, self.words.unfinished_words):
                break
            print(f"(Heard so far: {question!r}; waiting in case you go on...)")
            self.events("state", state="listening")
            more = record_question(blocks, rate, settings, wait_seconds=settings.extra_wait_seconds,
                                   noise=settings.min_level / settings.speech_ratio,
                                   on_level=self._level)
            if more is None:
                break  # you were finished after all
            audio = np.concatenate([audio, more])
            self.events("state", state="thinking")
            question = self.transcriber.transcribe(audio, rate)
        return question

    def _level(self, level: float) -> None:
        self.events("level", level=level)

    def context(self) -> str:
        """What Claude should know: the date and time, and where you are."""
        now = datetime.now()
        text = f"It is {now:%A %d %B %Y}, {now:%H:%M}"
        try:
            city = self.config.weather.city.strip()
            text += f", in {city or detect_location()[2]}"
        except Exception:
            pass
        return text + "."

    def warm_up(self) -> None:
        """Make the fixed recordings and find your location before the first clap."""
        name = self.config.user.address()
        for period in GREETINGS:
            self.recording(self.words.greeting(period, name))
        w = self.words
        for line in (w.no_weather, w.didnt_catch, w.no_brain, w.goodbye):
            self.recording(line)
        try:
            city = self.config.weather.city.strip()
            find_city(city) if city else detect_location()
        except Exception as exc:
            self.note(f"Couldn't find your location yet: {exc}")
        if self.config.listen.enabled:
            try:
                self.transcriber.load()
            except Exception as exc:
                self.note(f"Speech recognition isn't available: {exc}. "
                          "Install it with: pip install faster-whisper")
        self.events("ready")

    def talk(self) -> None:
        """Start a conversation straight away, without clapping (for --talk)."""
        clap = self.config.clap
        with recording(clap, choose_microphone(clap)) as blocks:
            self.converse(blocks)

    def greet_once(self) -> None:
        start = time.monotonic()
        self.wake_up()
        print(f"(Took {time.monotonic() - start:.1f} seconds, including speaking)")

    def run(self) -> None:
        print("Getting ready in the background...")
        threading.Thread(target=self.warm_up, name="warm-up", daemon=True).start()

        def on_double_clap(blocks) -> None:
            print("\nDouble clap heard!")
            self.wake_up()
            if self.config.listen.enabled:
                self.converse(blocks)
            self.events("state", state="waiting")
            print("\nListening for a double clap again...")

        print("Listening for a double clap... (press Ctrl+C to quit)")
        self.events("state", state="waiting")
        listen(self.config.clap, on_double_clap, on_clap=lambda: self.events("clap"))


def is_goodbye(text: str) -> bool:
    """True for "Thanks!", "No, that's all.", "Goodbye" and the like."""
    words = "".join(c if c.isalnum() or c in " '" else " " for c in text.lower()).split()
    short = " ".join(words)
    return len(words) <= 5 and any(
        f" {phrase} " in f" {short} " for phrase in all_goodbye_words())


def open_window(config: Config) -> bool:
    """Open her window; False if the window toolkit (PySide6) isn't installed."""
    try:
        from .window import run_window
    except ImportError as exc:
        print(f"(Her window isn't available ({exc}); running here instead. "
              "Install it with: pip install -r requirements.txt)")
        return False
    run_window(config)
    return True


def show_error(message: str) -> None:
    """A message box, for when there's no console to print to."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication([])
        QMessageBox.warning(None, "Assistentin", message)
        del app
    except Exception:
        pass


def make_shortcut(config: Config) -> None:
    from .shortcut import create_desktop_shortcut

    try:
        path = create_desktop_shortcut(phrases_for(config.user.language).app_title)
    except Exception as exc:
        print(f"Couldn't create the shortcut: {exc}")
        return
    print(f"Shortcut created: {path}")
    print("Double-click it to start her, no Command Prompt needed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clap-activated voice assistant")
    parser.add_argument("--config", type=Path, help="path to a config.toml file")
    parser.add_argument("--now", action="store_true",
                        help="greet once right away, without waiting for claps")
    parser.add_argument("--levels", action="store_true",
                        help="show microphone levels to tune the clap threshold")
    parser.add_argument("--devices", action="store_true", help="list the microphones")
    parser.add_argument("--say", metavar="TEXT", help="just speak TEXT (to test the voice)")
    parser.add_argument("--talk", action="store_true",
                        help="talk to her right away, without clapping")
    parser.add_argument("--console", action="store_true",
                        help="run in this console window instead of her own window")
    parser.add_argument("--shortcut", action="store_true",
                        help="put a shortcut on the desktop that opens her window")
    args = parser.parse_args()

    console_only = any((args.console, args.now, args.levels, args.devices, args.say, args.talk,
                        args.shortcut))
    try:
        config = load_config(args.config, report=True)
        print(f'She will call you: "{config.user.address()}"')
        if args.shortcut:
            make_shortcut(config)
            return
        if not console_only and open_window(config):
            return
        assistant = Assistant(config)
        if args.devices:
            list_devices()
        elif args.levels:
            show_levels(config.clap)
        elif args.say:
            assistant.speaker.say(args.say)
        elif args.now:
            assistant.greet_once()
        elif args.talk:
            assistant.talk()
        else:
            assistant.run()
    except ConfigError as exc:  # a mistake in config.toml: explain it, no traceback
        print(exc)
        if not console_only:
            show_error(str(exc))
    except KeyboardInterrupt:
        print("\nGoodbye!")


if __name__ == "__main__":
    main()
