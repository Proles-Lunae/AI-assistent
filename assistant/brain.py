"""The assistant's "brain": Claude, reached through your Claude Code login.

Instead of an API key, this runs the ``claude`` command (Claude Code) in
non-interactive mode, so it uses whatever account you're logged into with
``claude`` and its usage counts against that plan.

The greeting and temperature no longer need Claude (the sentence is fixed,
and asking Claude takes seconds), so nothing uses this at the moment; it's
kept ready for future features.
"""

from __future__ import annotations

import re
import shutil
import subprocess

from .config import BrainSettings

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
