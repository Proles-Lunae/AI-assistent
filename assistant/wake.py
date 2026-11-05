"""Wake her by saying her name ("Rose"), as well as by clapping.

While she waits for claps, every short bit of speech the microphone hears is
cut out and checked for her name with the speech recognition (on your own
PC, in the background, so clap detection carries on meanwhile). "Rose" on
its own wakes her like a double clap; "Rose, wie spät ist es?" wakes her
with that question.
"""

from __future__ import annotations

import queue
import threading
import unicodedata

import numpy as np

from .config import ListenSettings

# Greetings people put before a name; dropped from the start of the question.
FILLERS = {"hey", "hi", "hallo", "hello", "ok", "okay", "oh", "ähm", "äh", "na", "du", "also"}


def plain(word: str) -> str:
    """Lower case, without accents or punctuation: "Rosé," -> "rose"."""
    word = unicodedata.normalize("NFKD", word.lower())
    return "".join(c for c in word if c.isalnum() and not unicodedata.combining(c))


def find_wake_word(text: str, names: list[str]) -> str | None:
    """If ``text`` contains one of her ``names``, return what was said after it
    (the question, "" if nothing), else None.

    "Rose." -> "", "Hey Rose, wie spät ist es?" -> "wie spät ist es?",
    "Wie spät ist es, Rose?" -> "Wie spät ist es?"
    """
    wanted = {plain(n) for n in names if plain(n)}
    words = text.split()
    for i, word in enumerate(words):
        if plain(word) in wanted:
            after = words[i + 1:]
            before = [w for w in words[:i] if plain(w) not in FILLERS]
            if after:
                question = " ".join(after)
            elif before:  # "Wie spät ist es, Rose?": the question came first
                question = " ".join(before).rstrip(",;:") + "?" * text.rstrip().endswith("?")
            else:
                question = ""
            return question.strip(" ,;:-–").strip()
    return None


class SpeechCutter:
    """Cuts single utterances out of the stream of microphone blocks."""

    def __init__(self, sample_rate: int, settings: ListenSettings, quiet_end: float = 0.6,
                 shortest: float = 0.25, longest: float = 8.0):
        self.rate = sample_rate
        self.s = settings
        self.quiet_end = quiet_end  # this much quiet ends an utterance
        self.shortest = shortest  # shorter is a clap or a knock, not a word
        self.longest = longest  # longer is a conversation or the TV, not a call
        self.reset()

    def reset(self) -> None:
        self.noise = None
        self.heard: list[np.ndarray] = []
        self.talking = False
        self.quiet_for = 0.0
        self.loud_for = 0.0  # how long it was actually loud (a clap is very short)
        self.too_long = False

    def feed(self, block: np.ndarray):
        """Give it one block; returns an utterance (audio) when one has ended."""
        seconds = len(block) / self.rate
        level = float(np.sqrt(np.mean(np.square(block)))) if len(block) else 0.0
        if self.noise is None:
            self.noise = level
        start_level = max(self.noise * self.s.speech_ratio, self.s.min_level)
        if not self.talking:
            if level > start_level:
                self.talking, self.quiet_for, self.too_long = True, 0.0, False
                self.loud_for = seconds
                self.heard = self.heard[-12:] + [block]  # a moment before, too
            else:
                self.noise = 0.95 * self.noise + 0.05 * level
                self.heard = self.heard[-12:] + [block]
            return None
        loud = level > max(start_level * 0.5, self.noise * 1.5)
        self.quiet_for = 0.0 if loud else self.quiet_for + seconds
        if loud:
            self.loud_for += seconds
        if not self.too_long:
            self.heard.append(block)
            if len(self.heard) * seconds > self.longest:
                self.too_long, self.heard = True, []  # keep waiting for the end, drop it
        if self.quiet_for < self.quiet_end:
            return None
        self.talking = False
        audio, self.heard = self.heard, []
        if self.too_long or not audio:
            return None
        return np.concatenate(audio) if self.loud_for >= self.shortest else None


class WakeListener:
    """Listens for her name in the background while she waits for claps."""

    def __init__(self, transcriber, names: list[str], sample_rate: int,
                 settings: ListenSettings):
        self.transcriber = transcriber
        self.names = names
        self.rate = sample_rate
        self.cutter = SpeechCutter(sample_rate, settings)
        self.calls: queue.Queue[str] = queue.Queue()  # what was said after her name
        self.busy = threading.Event()
        self.round = 0  # results from before a reset are ignored

    def feed(self, block: np.ndarray) -> None:
        """Give it each microphone block while she waits for claps (cheap)."""
        audio = self.cutter.feed(block)
        if audio is None or self.busy.is_set():
            return  # nothing to check, or still checking the last one: skip this
        self.busy.set()
        threading.Thread(target=self._check, args=(audio, self.round),
                         name="wake-word", daemon=True).start()

    def _check(self, audio: np.ndarray, round_: int) -> None:
        try:
            text = self.transcriber.transcribe(audio, self.rate, quick=True,
                                               prompt=", ".join(self.names) + ".")
            question = find_wake_word(text, self.names)
            if question is not None and round_ == self.round:
                print(f"(Heard her name: {text!r})")
                self.calls.put(question)
        except Exception as exc:  # e.g. the speech model isn't ready yet
            print(f"(Couldn't check for her name: {exc})")
        finally:
            self.busy.clear()

    def take(self) -> str | None:
        """What was said after her name, if she was called; else None."""
        try:
            return self.calls.get_nowait()
        except queue.Empty:
            return None

    def reset(self) -> None:
        """Forget everything heard so far (e.g. while she's been talking herself)."""
        self.round += 1
        self.cutter.reset()
        while self.take() is not None:
            pass
