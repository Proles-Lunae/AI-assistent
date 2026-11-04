"""The assistant's "brain": Claude, reached through your Claude Code login.

Instead of an API key, this runs the ``claude`` command (Claude Code) in
non-interactive mode, so it uses whatever account you're logged into with
``claude`` and its usage counts against that plan.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime

from .config import BrainSettings
from .weather import WeatherReport

PERSONA = (
    "You are a warm, witty British voice assistant, a bit like a friendly butler. "
    "Everything you write is read aloud by a text-to-speech voice, so: write plain "
    "spoken sentences only, with no markdown, lists, emoji or symbols such as ° or %. "
    "Say 'degrees' and 'percent' as words. Don't call the user sir or madam. "
    "Keep replies short and natural."
)


class BrainError(RuntimeError):
    pass


def time_of_day(now: datetime) -> str:
    if now.hour < 5:
        return "night"
    if now.hour < 12:
        return "morning"
    if now.hour < 18:
        return "afternoon"
    return "evening"


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

    def greeting(self, name: str, weather: WeatherReport | None, now: datetime) -> str:
        """Ask Claude for a spoken greeting plus a weather briefing."""
        who = f"The user's name is {name}." if name else "You don't know the user's name."
        if weather:
            weather_part = (
                "Here is today's weather as JSON:\n"
                f"{json.dumps(weather.as_dict())}\n"
                "Give a quick weather briefing: what it's like now, today's high and "
                "low, and the chance of rain, plus one practical tip (umbrella, coat, "
                "sunglasses...)."
            )
        else:
            weather_part = (
                "The weather service couldn't be reached, so apologise briefly that "
                "you can't give the weather right now."
            )
        prompt = (
            f"The user just woke you up by clapping twice. It is {now:%A}, "
            f"{now:%H:%M} in the {time_of_day(now)}. {who}\n"
            "Greet them warmly for the time of day.\n"
            f"{weather_part}\n"
            "Keep the whole thing to three or four sentences."
        )
        return self.ask(prompt)


def fallback_greeting(name: str, weather: WeatherReport | None, now: datetime) -> str:
    """Used when Claude can't be reached, so the assistant still says something."""
    hello = f"Good {time_of_day(now)}" + (f", {name}" if name else "") + "."
    if time_of_day(now) == "night":
        hello = "Hello" + (f", {name}" if name else "") + ", you're up late."
    if weather:
        return f"{hello} {weather.summary()}"
    return f"{hello} I'm afraid I can't reach the weather service at the moment."
