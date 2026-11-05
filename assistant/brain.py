"""The assistant's "brain": Claude, reached through your Claude Code login.

Instead of an API key, this runs the ``claude`` command (Claude Code) in
non-interactive mode, so it uses whatever account you're logged into with
``claude`` and its usage counts against that plan.

The greeting and temperature don't need Claude (the sentence is fixed, and
asking Claude takes seconds); Claude answers the questions you ask her.
"""

from __future__ import annotations

import re
import json
import shutil
import subprocess
import sys
import threading
from typing import Iterator

from .config import BrainSettings

PERSONA = (
    "You are a warm, witty voice assistant, a bit like a friendly British butler. "
    "Everything you write is read aloud by a text-to-speech voice, so: write plain "
    "spoken sentences only, with no markdown, lists, emoji or symbols such as ° or %; "
    "write units like degrees and percent as words. "
    "Keep replies short and natural."
)


class BrainError(RuntimeError):
    pass


def first_sentence(text: str) -> str:
    """Keep only the first sentence, in case Claude wrote more."""
    return re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]


class ClaudeBrain:
    MAX_HISTORY = 6  # how many earlier questions and answers she remembers

    def __init__(self, settings: BrainSettings):
        self.s = settings

    def _command(self, output: str) -> list[str]:
        # Full path, so Windows finds claude.exe or claude.cmd.
        command = shutil.which(self.s.command)
        if command is None:
            raise BrainError(
                f"Can't find the '{self.s.command}' command. Install Claude Code and "
                "run 'claude' once to log in."
            )
        # --tools "": no file or shell access needed; it only has to talk. The
        # last two skip start-up work it doesn't need (MCP servers, skills and
        # slash commands).
        cmd = [command, "-p", "--system-prompt", PERSONA, "--tools", "",
               "--output-format", output, "--no-session-persistence",
               "--strict-mcp-config", "--disable-slash-commands"]
        if output == "stream-json":  # the answer word by word, as it's written
            cmd += ["--verbose", "--include-partial-messages"]
        if self.s.model:
            cmd += ["--model", self.s.model]
        return cmd

    def ask(self, prompt: str) -> str:
        """Send one prompt to Claude and return its reply as text."""
        cmd = self._command("text")
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

    def ask_in_sentences(self, prompt: str) -> Iterator[str]:
        """Like ask(), but hands over each sentence as soon as Claude has written it,
        so she can start speaking while the rest is still being written."""
        proc = subprocess.Popen(self._command("stream-json"), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8")
        timed_out = threading.Event()

        def too_slow() -> None:
            timed_out.set()
            stop_process(proc)

        watchdog = threading.Timer(self.s.timeout, too_slow)
        watchdog.start()
        written, final, said_any = "", None, False
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
            for line in proc.stdout:
                event = parse_event(line)
                if event is None:
                    continue
                if event.get("type") == "result":
                    final = event.get("result") or ""
                    continue
                piece = text_delta(event)
                if not piece:
                    continue
                written += piece
                sentences, written = split_sentences(written)
                for sentence in sentences:
                    said_any = True
                    yield sentence
            proc.wait()
        finally:
            watchdog.cancel()
            if proc.poll() is None:  # e.g. the conversation ended early
                stop_process(proc)
        if timed_out.is_set() and not said_any:
            raise BrainError("Claude took too long to answer")
        rest = written.strip() or ("" if said_any else (final or "").strip())
        if rest:
            yield rest
            said_any = True
        if not said_any:
            detail = proc.stderr.read().strip()[:300] if proc.stderr else ""
            raise BrainError(f"Claude didn't answer (exit {proc.returncode}): {detail}")

    def answer(self, question: str, history: list[tuple[str, str]], context: str,
               address: str = "sir", instruction: str = "Answer in English.") -> str:
        """Answer a spoken question, remembering the conversation so far."""
        return self.ask(self.answer_prompt(question, history, context, address, instruction))

    def answer_in_sentences(self, question: str, history: list[tuple[str, str]], context: str,
                            address: str = "sir",
                            instruction: str = "Answer in English.") -> Iterator[str]:
        """The answer sentence by sentence, as Claude writes it (faster to speak)."""
        return self.ask_in_sentences(
            self.answer_prompt(question, history, context, address, instruction))

    def answer_prompt(self, question: str, history: list[tuple[str, str]], context: str,
                      address: str, instruction: str) -> str:
        lines = [f"Context: {context}"]
        if history:
            lines.append("The conversation so far:")
            for asked, answered in history[-self.MAX_HISTORY:]:
                lines += [f"User: {asked}", f"You: {answered}"]
        lines += [
            "The user just said this (turned into text from speech, so it may have "
            f'small mistakes): "{question}"',
            f"Answer in at most three short spoken sentences. You may call the user "
            f"'{address}' now and then. {instruction}",
        ]
        return "\n".join(lines)


# Words after which a full stop doesn't end the sentence ("z.B.", "Dr.", ...).
ABBREVIATIONS = {"z.b", "d.h", "dr", "nr", "ca", "usw", "bzw", "evtl", "ggf", "inkl", "vgl", "st",
                 "mr", "mrs", "ms", "e.g", "i.e", "etc", "vs", "no", "jan", "feb", "aug", "sept",
                 "okt", "nov", "dez", "dec"}


def split_sentences(text: str) -> tuple[list[str], str]:
    """Split off the finished sentences; return them and the unfinished rest.

    A sentence ends at ".", "!" or "?" followed by a space or a new line, but
    not after a number ("am 28. August") or an abbreviation ("z.B.").
    """
    sentences, start = [], 0
    for i, char in enumerate(text):
        if char not in ".!?" or i + 1 >= len(text) or not text[i + 1].isspace():
            continue
        word = text[start:i].split()[-1].lower() if text[start:i].split() else ""
        if char == "." and (word.isdigit() or word.rstrip(".") in ABBREVIATIONS or len(word) == 1):
            continue
        sentence = text[start:i + 1].strip()
        if sentence:
            sentences.append(sentence)
        start = i + 1
    return sentences, text[start:]


def parse_event(line: str) -> dict | None:
    try:
        event = json.loads(line)
    except ValueError:
        return None
    return event if isinstance(event, dict) else None


def text_delta(event: dict) -> str:
    """The new bit of answer text in a stream-json event, if any."""
    if event.get("type") != "stream_event":
        return ""
    inner = event.get("event") or {}
    delta = inner.get("delta") or {}
    if inner.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
        return delta.get("text") or ""
    return ""


def stop_process(proc: subprocess.Popen) -> None:
    """Stop Claude Code. On Windows the whole process tree, since claude.cmd
    starts Node in a child process that a plain kill would leave running."""
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10)
        else:
            proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass
