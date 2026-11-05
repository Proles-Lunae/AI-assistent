"""Run the assistant: wait for a double clap, then greet you with the temperature."""

from __future__ import annotations

import argparse
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from .config import Config, ConfigError, load_config
from .microphone import list_devices, listen, show_levels
from .timeframes import GREETINGS, frame_end, frame_start, standard_greeting, time_of_day
from .voice import Speaker, Speech
from .weather import detect_location, find_city, get_weather

NO_WEATHER = "I'm afraid I can't reach the weather service at the moment."
WEATHER_WAIT = 15.0  # seconds; after this, give up on the weather for this clap


class Assistant:
    def __init__(self, config: Config):
        self.config = config
        self.speaker = Speaker(config.voice)
        self._ready: dict[str, Speech] = {}  # greetings and the no-weather line, by text
        self._pool = ThreadPoolExecutor(max_workers=2)

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

    def warm_up(self) -> None:
        """Make the fixed recordings and find your location before the first clap."""
        name = self.config.user.address()
        for period in GREETINGS:
            self.recording(standard_greeting(period, name))
        self.recording(NO_WEATHER)
        try:
            city = self.config.weather.city.strip()
            find_city(city) if city else detect_location()
        except Exception as exc:
            print(f"(Couldn't find your location yet: {exc})")

    def greet_once(self) -> None:
        start = time.monotonic()
        self.wake_up()
        print(f"(Took {time.monotonic() - start:.1f} seconds, including speaking)")

    def run(self) -> None:
        print("Getting ready in the background...")
        threading.Thread(target=self.warm_up, name="warm-up", daemon=True).start()

        def on_double_clap() -> None:
            print("\nDouble clap heard!")
            self.wake_up()
            print("\nListening for a double clap again...")

        print("Listening for a double clap... (press Ctrl+C to quit)")
        listen(self.config.clap, on_double_clap)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clap-activated voice assistant")
    parser.add_argument("--config", type=Path, help="path to a config.toml file")
    parser.add_argument("--now", action="store_true",
                        help="greet once right away, without waiting for claps")
    parser.add_argument("--levels", action="store_true",
                        help="show microphone levels to tune the clap threshold")
    parser.add_argument("--devices", action="store_true", help="list the microphones")
    parser.add_argument("--say", metavar="TEXT", help="just speak TEXT (to test the voice)")
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
        else:
            assistant.run()
    except ConfigError as exc:  # a mistake in config.toml: explain it, no traceback
        print(exc)
    except KeyboardInterrupt:
        print("\nGoodbye!")


if __name__ == "__main__":
    main()
