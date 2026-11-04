"""Run the assistant: wait for a double clap, then greet you with the weather."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from .brain import BrainError, ClaudeBrain, fallback_greeting
from .clap_detector import DoubleClapDetector, show_levels
from .config import Config, load_config
from .voice import Speaker
from .weather import get_weather


class Assistant:
    def __init__(self, config: Config):
        self.config = config
        self.brain = ClaudeBrain(config.brain)
        self.speaker = Speaker(config.voice)

    def build_greeting(self) -> str:
        now = datetime.now()
        name = self.config.user.name
        try:
            weather = get_weather(self.config.weather.city, self.config.weather.units)
        except Exception as exc:
            print(f"(Couldn't get the weather: {exc})")
            weather = None
        try:
            return self.brain.greeting(name, weather, now)
        except BrainError as exc:
            print(f"(Claude unavailable, using a simple greeting: {exc})")
            return fallback_greeting(name, weather, now)

    def wake_up(self) -> None:
        print("\nDouble clap heard! Thinking...")
        self.speaker.say(self.build_greeting())
        print("\nListening for a double clap again...")

    def run(self) -> None:
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
            assistant.wake_up()
        else:
            assistant.run()
    except KeyboardInterrupt:
        print("\nGoodbye!")


if __name__ == "__main__":
    main()
