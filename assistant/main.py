"""Run the assistant: wait for a double clap, then greet you with the weather."""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

from .brain import BrainError, ClaudeBrain
from .briefing import Briefing, BriefingCache
from .config import Config, ConfigError, load_config
from .microphone import list_devices, listen, show_levels
from .timeframes import frame_end, frame_start, standard_greeting, time_of_day
from .voice import Speaker
from .weather import get_weather

NO_WEATHER = "I'm afraid I can't reach the weather service at the moment."


class Assistant:
    def __init__(self, config: Config):
        self.config = config
        self.brain = ClaudeBrain(config.brain)
        self.speaker = Speaker(config.voice)
        self.cache: BriefingCache | None = None

    def build_briefing(self, start: datetime, quick: bool = False) -> Briefing:
        """Greeting + forecast for the frame at ``start``, as one recording.

        Normally the forecast is Claude's wording (takes several seconds). The
        ``quick`` version puts the weather in a built-in sentence instead (~1-2 s).
        """
        period = time_of_day(start)
        settings = self.config.weather
        try:
            weather = get_weather(settings.city, settings.units, start, frame_end(start))
        except Exception as exc:
            print(f"(Couldn't get the weather: {exc})")
            weather = None
        forecast = NO_WEATHER if weather is None else weather.summary(period)
        complete = weather is not None and not quick  # if not, it's a stand-in, replaced soon
        if complete:
            try:
                forecast = self.brain.weather_briefing(weather, start)
            except BrainError as exc:
                print(f"(Claude unavailable, using a simple forecast: {exc})")
        greeting = standard_greeting(period, self.config.user.address())
        speech = self.speaker.prepare(f"{greeting} {forecast}")
        return Briefing(speech=speech, frame=start, made_at=time.monotonic(), complete=complete)

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
        elif (briefing := self.cache.take()) is None:
            # Claude's version isn't ready yet (just started, or the PC was
            # asleep): use the quick version so you aren't kept waiting.
            print("(Using the quick forecast; Claude's is still being prepared.)")
            quick = self.build_briefing(frame, quick=True)
            self.cache.offer(quick)  # reused by the next clap until Claude's is ready
            briefing = self.cache.take() or quick  # Claude's may be done by now
        self.speaker.play(briefing.speech)  # greeting and forecast in one message
        print("\nListening for a double clap again...")

    def run(self) -> None:
        if self.config.briefing.prepare_ahead:
            print("Preparing the greeting and weather in the background...")
            self.cache = BriefingCache(self.build_briefing)
            self.cache.start()
        print("Listening for a double clap... (press Ctrl+C to quit)")
        listen(self.config.clap, self.wake_up)


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
