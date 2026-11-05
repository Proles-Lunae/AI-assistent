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
from .listening import Transcriber, drain, record_question
from .microphone import choose_microphone, list_devices, listen, recording, show_levels
from .timeframes import GREETINGS, frame_end, frame_start, standard_greeting, time_of_day
from .voice import Speaker, Speech
from .weather import detect_location, find_city, get_weather

NO_WEATHER = "I'm afraid I can't reach the weather service at the moment."
WEATHER_WAIT = 15.0  # seconds; after this, give up on the weather for this clap
DIDNT_CATCH = "Sorry, I didn't catch that."
NO_BRAIN = "I'm sorry, I can't think straight at the moment. Please try again later."
GOODBYE = "You're welcome. Just clap if you need me."
# Saying one of these (on its own, or in a short sentence) ends the conversation.
GOODBYE_WORDS = ("thank you", "thanks", "goodbye", "bye", "that's all", "that is all",
                 "nothing", "no thanks", "stop", "never mind")


class Assistant:
    def __init__(self, config: Config):
        self.config = config
        self.speaker = Speaker(config.voice)
        self._ready: dict[str, Speech] = {}  # greetings and the no-weather line, by text
        self._pool = ThreadPoolExecutor(max_workers=2)
        self.brain = ClaudeBrain(config.brain)
        self.transcriber = Transcriber(config.listen)

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
            print(f"(Couldn't get the weather: {exc})")
            return self.recording(NO_WEATHER)
        return self.speaker.prepare(weather.spoken(time_of_day(now)))

    def wake_up(self) -> None:
        """Greet at once; the weather is checked fresh while the greeting plays."""
        now = datetime.now()
        weather = self._pool.submit(self.weather_speech, now)
        greeting = standard_greeting(time_of_day(now), self.config.user.address())
        self.speaker.play(self.recording(greeting), wait=False)
        try:
            speech = weather.result(timeout=WEATHER_WAIT)
        except Exception as exc:
            print(f"(The weather took too long: {exc})")
            speech = self.recording(NO_WEATHER)
        self.speaker.finish()  # let the greeting end, then carry straight on
        self.speaker.play(speech)

    def converse(self, blocks) -> None:
        """Listen for questions and answer them, until you're done or go quiet."""
        rate = self.config.clap.sample_rate
        history: list[tuple[str, str]] = []
        while True:
            self.speaker.beep()
            drain(blocks)  # forget what the microphone heard while she was talking
            print("Listening to you... (just stay quiet to stop)")
            audio = record_question(blocks, rate, self.config.listen)
            if audio is None:
                print("(Nothing heard.)")
                return
            try:
                question = self.transcriber.transcribe(audio, rate)
            except Exception as exc:  # e.g. faster-whisper not installed
                print(f"(Couldn't turn your speech into text: {exc})")
                return
            if not question:
                self.speaker.say(self.recording(DIDNT_CATCH).text)
                continue
            print(f"You: {question}")
            if is_goodbye(question):
                self.speaker.play(self.recording(GOODBYE))
                return
            print("(Thinking...)")
            try:
                answer = self.brain.answer(question, history, self.context(),
                                           self.config.user.address())
            except BrainError as exc:
                print(f"(Claude couldn't answer: {exc})")
                self.speaker.play(self.recording(NO_BRAIN))
                return
            history.append((question, answer))
            self.speaker.say(answer)

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
            self.recording(standard_greeting(period, name))
        for line in (NO_WEATHER, DIDNT_CATCH, NO_BRAIN, GOODBYE):
            self.recording(line)
        try:
            city = self.config.weather.city.strip()
            find_city(city) if city else detect_location()
        except Exception as exc:
            print(f"(Couldn't find your location yet: {exc})")
        if self.config.listen.enabled:
            try:
                self.transcriber.load()
            except Exception as exc:
                print(f"(Speech recognition isn't available: {exc}. "
                      "Install it with: pip install faster-whisper)")

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
            print("\nListening for a double clap again...")

        print("Listening for a double clap... (press Ctrl+C to quit)")
        listen(self.config.clap, on_double_clap)


def is_goodbye(text: str) -> bool:
    """True for "Thanks!", "No, that's all.", "Goodbye" and the like."""
    words = "".join(c if c.isalnum() or c in " '" else " " for c in text.lower()).split()
    short = " ".join(words)
    return len(words) <= 5 and any(
        f" {phrase} " in f" {short} " for phrase in GOODBYE_WORDS)


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
    args = parser.parse_args()

    try:
        config = load_config(args.config, report=True)
        print(f'She will call you: "{config.user.address()}"')
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
    except KeyboardInterrupt:
        print("\nGoodbye!")


if __name__ == "__main__":
    main()
