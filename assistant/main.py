"""Run the assistant: wait for a double clap, then greet you with the weather."""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

from .brain import (
    NO_WEATHER,
    BrainError,
    ClaudeBrain,
    frame_end,
    frame_start,
    standard_greeting,
    time_of_day,
)
from .briefing import Briefing, BriefingCache
from .clap_detector import DoubleClapDetector, list_devices, show_levels
from .config import Config, ConfigError, load_config
from .voice import Speaker
from .weather import get_weather


class Assistant:
    def __init__(self, config: Config):
        self.config = config
        self.brain = ClaudeBrain(config.brain)
        self.speaker = Speaker(config.voice)
        self.cache: BriefingCache | None = None

    def greeting_text(self, period: str) -> str:
        return standard_greeting(period, self.config.user.address())

    def fetch_weather(self, start: datetime):
        try:
            return get_weather(
                self.config.weather.city, self.config.weather.units, start, frame_end(start)
            )
        except Exception as exc:
            print(f"(Couldn't get the weather: {exc})")
            return None

    def weather_text(self, start: datetime) -> tuple[str, bool]:
        """Return (forecast for the frame at ``start``, whether weather was included)."""
        weather = self.fetch_weather(start)
        if weather is None:
            return NO_WEATHER, False
        try:
            return self.brain.weather_briefing(weather, start), True
        except BrainError as exc:
            print(f"(Claude unavailable, using a simple forecast: {exc})")
            return weather.summary(time_of_day(start)), True

    def make_briefing(self, start: datetime, weather_text: str, complete: bool) -> Briefing:
        """Greeting + forecast for the frame at ``start``, as one recording."""
        greeting = self.greeting_text(time_of_day(start))
        return Briefing(
            speech=self.speaker.prepare(f"{greeting} {weather_text}"),
            weather_text=weather_text,
            frame=start,
            made_at=time.monotonic(),
            complete=complete,
        )

    def build_briefing(self, start: datetime) -> Briefing:
        """The full version, with Claude's wording (takes several seconds)."""
        return self.make_briefing(start, *self.weather_text(start))

    def quick_briefing(self, start: datetime) -> Briefing:
        """A fast version without Claude: the weather in a built-in sentence (~1-2 s)."""
        weather = self.fetch_weather(start)
        text = NO_WEATHER if weather is None else weather.summary(time_of_day(start))
        return self.make_briefing(start, text, complete=False)  # Claude's replaces it

    def greet_once(self) -> None:
        """Greet and give the forecast right away (no preparing ahead)."""
        start = time.monotonic()
        briefing = self.build_briefing(frame_start(datetime.now()))
        print(f"(Ready after {time.monotonic() - start:.1f} seconds)")
        self.speaker.play(briefing.speech)

    def wake_up(self) -> None:
        print("\nDouble clap heard!")
        frame = frame_start(datetime.now())
        if self.cache is None:  # prepare_ahead is off: ask Claude now
            briefing = self.build_briefing(frame)
        else:
            briefing = self.cache.take()
            if briefing is None:
                # Claude's version isn't ready yet (just started, or the PC was
                # asleep): use the quick version so you aren't kept waiting.
                print("(Using the quick forecast; Claude's is still being prepared.)")
                quick = self.quick_briefing(frame)
                self.cache.offer(quick)  # reused by the next clap until Claude's is ready
                briefing = self.cache.take() or quick  # Claude's may be done by now
        self.speaker.play(briefing.speech)  # greeting and forecast in one message
        print("\nListening for a double clap again...")

    def run(self) -> None:
        if self.config.briefing.prepare_ahead:
            print("Preparing the greeting and weather in the background...")
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

    try:
        config = load_config(args.config, report=True)
    except ConfigError as exc:
        print(exc)
        return
    print(f'She will call you: "{config.user.address()}"')
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
