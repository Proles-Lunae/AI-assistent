"""The assistant's "brain": Claude, reached through your Claude Code login.

Instead of an API key, this runs the ``claude`` command (Claude Code) in
non-interactive mode, so it uses whatever account you're logged into with
``claude`` and its usage counts against that plan.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta

from .config import BrainSettings
from .weather import WeatherReport

PERSONA = (
    "You are a warm, witty British voice assistant, a bit like a friendly butler. "
    "Everything you write is read aloud by a text-to-speech voice, so: write plain "
    "spoken sentences only, with no markdown, lists, emoji or symbols such as ° or %. "
    "Say 'degrees' and 'percent' as words. Don't call the user sir or madam. "
    "Keep replies short and natural."
)

# The day is split into three time frames, each with its own greeting.
# (name, first hour, end hour, greeting)
TIME_FRAMES = (
    ("morning", 3, 11, "Good morning"),
    ("afternoon", 11, 18, "Good afternoon"),
    ("evening", 18, 3, "Good evening"),  # runs past midnight until 3am
)
GREETINGS = {name: greeting for name, _, _, greeting in TIME_FRAMES}
NO_WEATHER = "I'm afraid I can't reach the weather service at the moment."


class BrainError(RuntimeError):
    pass


def time_of_day(now: datetime) -> str:
    """'morning' (3am-11am), 'afternoon' (11am-6pm) or 'evening' (6pm-3am)."""
    if 3 <= now.hour < 11:
        return "morning"
    if 11 <= now.hour < 18:
        return "afternoon"
    return "evening"


def frame_start(now: datetime) -> datetime:
    """When the current time frame began, e.g. 6pm yesterday at 1am.

    This tells one evening apart from the next, even if the computer slept
    in between.
    """
    hour = {"morning": 3, "afternoon": 11, "evening": 18}[time_of_day(now)]
    start = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if start > now:  # after midnight: the evening started yesterday
        start -= timedelta(days=1)
    return start


def standard_greeting(period: str, name: str = "") -> str:
    return GREETINGS[period] + (f", {name}" if name else "") + "."


class ClaudeBrain:
    def __init__(self, settings: BrainSettings):
        self.s = settings

    def available(self) -> bool:
        return shutil.which(self.s.command) is not None

    def ask(self, prompt: str) -> str:
        """Send one prompt to Claude and return its reply as text."""
        # Full path, so Windows finds claude.exe or claude.cmd.
        command = shutil.which(self.s.command)
        if command is None:
            raise BrainError(
                f"Can't find the '{self.s.command}' command. Install Claude Code and "
                "run 'claude' once to log in."
            )
        # The prompt goes in through stdin, not as an argument: on Windows a
        # multi-line argument gets cut off when claude is a .cmd script.
        cmd = [
            command,
            "-p",
            "--system-prompt",
            PERSONA,
            "--tools",
            "",  # No file or shell access needed; it only has to talk.
            "--output-format",
            "text",
            "--no-session-persistence",
        ]
        if self.s.model:
            cmd += ["--model", self.s.model]
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.s.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise BrainError("Claude took too long to answer") from exc
        reply = result.stdout.strip()
        if result.returncode != 0 or not reply:
            detail = (result.stderr or result.stdout).strip()[:300]
            raise BrainError(f"Claude didn't answer (exit {result.returncode}): {detail}")
        return reply

    def weather_briefing(self, weather: WeatherReport, now: datetime) -> str:
        """Ask Claude for a short spoken weather briefing (no greeting)."""
        period = time_of_day(now)
        prompt = (
            f"You have just greeted the user with '{GREETINGS[period]}'. Do not greet "
            f"them again. It is {now:%A} {period}.\n"
            "Here is the weather as JSON:\n"
            f"{json.dumps(weather.as_dict())}\n"
            f"Give a quick weather briefing for the {period}: what it's like, the high "
            "and low, and the chance of rain, plus one practical tip (umbrella, coat, "
            "sunglasses...). Two or three sentences."
        )
        return self.ask(prompt)
