"""The assistant's "brain": Claude, reached through your Claude Code login.

Instead of an API key, this runs the ``claude`` command (Claude Code) in
non-interactive mode, so it uses whatever account you're logged into with
``claude`` and its usage counts against that plan.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime

from .config import BrainSettings
from .timeframes import GREETINGS, frame_end, time_of_day
from .weather import WeatherReport

PERSONA = (
    "You are a warm, witty British voice assistant, a bit like a friendly butler. "
    "Everything you write is read aloud by a text-to-speech voice, so: write plain "
    "spoken sentences only, with no markdown, lists, emoji or symbols such as ° or %. "
    "Say 'degrees' and 'percent' as words. "
    "Keep replies short and natural."
)


class BrainError(RuntimeError):
    pass


def first_sentence(text: str) -> str:
    """Keep only the first sentence, in case Claude wrote more."""
    return re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]


class ClaudeBrain:
    def __init__(self, settings: BrainSettings):
        self.s = settings

    def ask(self, prompt: str) -> str:
        """Send one prompt to Claude and return its reply as text."""
        # Full path, so Windows finds claude.exe or claude.cmd.
        command = shutil.which(self.s.command)
        if command is None:
            raise BrainError(
                f"Can't find the '{self.s.command}' command. Install Claude Code and "
                "run 'claude' once to log in."
            )
        # --tools "": no file or shell access needed; it only has to talk. The
        # last two skip start-up work a weather sentence doesn't need (MCP
        # servers, skills and slash commands): about 0.1 s faster when measured.
        cmd = [command, "-p", "--system-prompt", PERSONA, "--tools", "",
               "--output-format", "text", "--no-session-persistence",
               "--strict-mcp-config", "--disable-slash-commands"]
        if self.s.model:
            cmd += ["--model", self.s.model]
        try:
            # The prompt goes in through stdin, not as an argument: on Windows a
            # multi-line argument gets cut off when claude is a .cmd script.
            result = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                                    encoding="utf-8", timeout=self.s.timeout)
        except subprocess.TimeoutExpired as exc:
            raise BrainError("Claude took too long to answer") from exc
        reply = result.stdout.strip()
        if result.returncode != 0 or not reply:
            detail = (result.stderr or result.stdout).strip()[:300]
            raise BrainError(f"Claude didn't answer (exit {result.returncode}): {detail}")
        return reply

    def weather_briefing(self, weather: WeatherReport, start: datetime) -> str:
        """Ask Claude for a one-sentence forecast for the time frame at ``start``."""
        period = time_of_day(start)
        facts = weather.spoken_facts()
        rain = ("and the chance of rain" if "rain_chance_percent" in facts
                else "and do not mention any chance of rain")
        prompt = (
            f"You have just greeted the user with '{GREETINGS[period]}'. Do not greet "
            f"them again. This is for {start:%A} {period}.\n"
            "Here is the weather as JSON; temperature is the latest measured one, "
            f"conditions are for the {period} ({start:%H:%M} to {frame_end(start):%H:%M}):\n"
            f"{json.dumps(facts)}\n"
            f"Give the weather in ONE short spoken sentence of at most 20 words: the "
            f"conditions, the temperature {rain}. No high or low. Nothing else."
        )
        return first_sentence(self.ask(prompt))
