"""Run the assistant: wait for a double clap, then greet you with the weather."""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

from .brain import (
    GREETINGS,
    NO_WEATHER,
    BrainError,
    ClaudeBrain,
    frame_start,
    standard_greeting,
    time_of_day,
)
from .briefing import Briefing, BriefingCache
from .clap_detector import DoubleClapDetector, list_devices, show_levels
from .config import Config, load_config
from .voice import Speaker, Speech
from .weather import get_weather


class Assistant:
    def __init__(self, config: Config):
        self.config = config
        self.brain = ClaudeBrain(config.brain)
        self.speaker = Speaker(config.voice)
        self.cache: BriefingCache | None = None
        self.greetings: dict[str, Speech] = {}

    def greeting_text(self, period: str) -> str:
        return standard_greeting(period, self.config.user.name)

    def weather_text(self) -> tuple[str, bool]:
        """Return (weather briefing text, whether the weather was included)."""
        now = datetime.now()
        try:
            weather = get_weather(self.config.weather.city, self.config.weather.units)
        except Exception as exc:
            print(f"(Couldn't get the weather: {exc})")
            return NO_WEATHER, False
        try:
            return self.brain.weather_briefing(weather, now), True
        except BrainError as exc:
            print(f"(Claude unavailable, using a simple weather report: {exc})")
            return weather.summary(), True

    def build_briefing(self) -> Briefing:
        frame = frame_start(datetime.now())
        text, complete = self.weather_text()
        return Briefing(
            speech=self.speaker.prepare(text),
            frame=frame,
            made_at=time.monotonic(),
            complete=complete,
        )

    def greet_once(self) -> None:
        """Greet and give the weather right away (no preparing ahead)."""
        self.speaker.say(self.greeting_text(time_of_day(datetime.now())))
        start = time.monotonic()
        briefing = self.build_briefing()
        print(f"(Weather briefing ready after {time.monotonic() - start:.1f} seconds)")
        self.speaker.play(briefing.speech)

    def wake_up(self) -> None:
        print("\nDouble clap heard!")
        period = time_of_day(datetime.now())
        greeting = self.greetings.get(period)
        if greeting is None:
            self.speaker.say(self.greeting_text(period))
        else:
            self.speaker.play(greeting)
        briefing = None
        if self.cache:
            briefing = self.cache.take(timeout=self.config.brain.timeout + 30)
        if briefing is None:
            briefing = self.build_briefing()
        self.speaker.play(briefing.speech)
        print("\nListening for a double clap again...")

    def run(self) -> None:
        if self.config.briefing.prepare_ahead:
            print("Preparing the greetings and weather in the background...")
            self.greetings = {p: self.speaker.prepare(self.greeting_text(p)) for p in GREETINGS}
            self.cache = BriefingCache(self.build_briefing)
            self.cache.start()
        detector = DoubleClapDetector(self.config.clap)
        print("Listening for a double clap... (press Ctrl+C to quit)")
        detector.listen(self.wake_up)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clap-activated voice assistant")
    parser.add_argument("--config", type=Path, help="path to a config.toml file")
    parser.add_argument(
        "--now", action="store_true", help="greet once right away, without waiting for claps"
    )
    parser.add_argument(
        "--levels", action="store_true", help="show microphone levels to tune the clap threshold"
    )
    parser.add_argument("--devices", action="store_true", help="list the microphones")
    parser.add_argument("--say", metavar="TEXT", help="just speak TEXT (to test the voice)")
    args = parser.parse_args()

    config = load_config(args.config)
    assistant = Assistant(config)
    try:
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
    except KeyboardInterrupt:
        print("\nGoodbye!")


if __name__ == "__main__":
    main()
