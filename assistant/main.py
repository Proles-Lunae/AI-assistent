"""Run the assistant: wait for a double clap, then greet you with the weather."""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

from .brain import BrainError, ClaudeBrain, fallback_greeting, time_of_day
from .briefing import Briefing, BriefingCache
from .clap_detector import DoubleClapDetector, show_levels
from .config import Config, load_config
from .voice import Speaker
from .weather import get_weather

ONE_MOMENT = "One moment, let me check the weather."


class Assistant:
    def __init__(self, config: Config):
        self.config = config
        self.brain = ClaudeBrain(config.brain)
        self.speaker = Speaker(config.voice)
        self.cache: BriefingCache | None = None
        self.one_moment = None

    def build_greeting(self) -> tuple[str, bool]:
        """Return (greeting text, whether the weather was included)."""
        now = datetime.now()
        name = self.config.user.name
        try:
            weather = get_weather(self.config.weather.city, self.config.weather.units)
        except Exception as exc:
            print(f"(Couldn't get the weather: {exc})")
            weather = None
        try:
            text = self.brain.greeting(name, weather, now)
        except BrainError as exc:
            print(f"(Claude unavailable, using a simple greeting: {exc})")
            text = fallback_greeting(name, weather, now)
        return text, weather is not None

    def build_briefing(self) -> Briefing:
        text, complete = self.build_greeting()
        return Briefing(
            speech=self.speaker.prepare(text),
            made_at=time.monotonic(),
            period=time_of_day(datetime.now()),
            complete=complete,
        )

    def greet_once(self) -> None:
        """Make a greeting and speak it (no preparing ahead)."""
        start = time.monotonic()
        briefing = self.build_briefing()
        print(f"(Ready after {time.monotonic() - start:.1f} seconds)")
        self.speaker.play(briefing.speech)

    def wake_up(self) -> None:
        print("\nDouble clap heard!")
        briefing = self.cache.take() if self.cache else None
        if briefing is None:
            # Nothing prepared yet (e.g. just started): say something right away.
            if self.one_moment is not None:
                self.speaker.play(self.one_moment)
            if self.cache:
                briefing = self.cache.take(timeout=self.config.brain.timeout + 30)
            if briefing is None:
                briefing = self.build_briefing()
        self.speaker.play(briefing.speech)
        print("\nListening for a double clap again...")

    def run(self) -> None:
        if self.config.briefing.prepare_ahead:
            print("Preparing the first greeting in the background...")
            self.one_moment = self.speaker.prepare(ONE_MOMENT)
            self.cache = BriefingCache(
                self.build_briefing, max_age=self.config.briefing.refresh_minutes * 60
            )
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
    parser.add_argument("--say", metavar="TEXT", help="just speak TEXT (to test the voice)")
    args = parser.parse_args()

    config = load_config(args.config)
    assistant = Assistant(config)
    try:
        if args.levels:
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
