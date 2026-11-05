"""Hear what you say: record one question from the microphone and turn it into text.

Recording stops by itself once you've been quiet for a moment. The speech is
turned into text on your own PC with Whisper (the faster-whisper package), so
your voice isn't sent anywhere. The first time, Whisper downloads its model
(about 140 MB for "base").
"""

from __future__ import annotations

import queue
import time

import numpy as np

from .config import ListenSettings

WHISPER_RATE = 16000  # Whisper expects 16 kHz audio


def record_question(blocks: queue.Queue, sample_rate: int, settings: ListenSettings):
    """Record from ``blocks`` until you stop talking.

    Waits up to ``wait_seconds`` for you to start, then stops after
    ``silence_seconds`` of quiet (or ``max_seconds`` in total). Returns the
    audio as one array, or None if you didn't say anything.
    """
    block_seconds = None
    heard: list[np.ndarray] = []
    noise = None  # background loudness, learned from the first blocks
    talking = False
    quiet_for = 0.0
    waited = 0.0
    while True:
        try:
            block = blocks.get(timeout=1.0)
        except queue.Empty:
            return None  # the microphone stopped sending audio
        block_seconds = block_seconds or len(block) / sample_rate
        level = float(np.sqrt(np.mean(np.square(block)))) if len(block) else 0.0
        if noise is None:
            noise = level
        loud = level > max(noise * settings.speech_ratio, settings.min_level)
        if not talking:
            waited += block_seconds
            if loud:
                talking = True
                heard.append(block)
            elif waited > settings.wait_seconds:
                return None
            else:
                noise = 0.9 * noise + 0.1 * level  # keep learning the room's noise
                heard = heard[-3:] + [block]  # keep a moment before you start talking
            continue
        heard.append(block)
        quiet_for = 0.0 if loud else quiet_for + block_seconds
        if quiet_for >= settings.silence_seconds or len(heard) * block_seconds >= settings.max_seconds:
            return np.concatenate(heard)


def to_whisper_rate(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Resample the microphone audio to the 16 kHz Whisper expects."""
    if sample_rate == WHISPER_RATE:
        return audio.astype(np.float32)
    length = int(len(audio) * WHISPER_RATE / sample_rate)
    positions = np.linspace(0, len(audio) - 1, length)
    return np.interp(positions, np.arange(len(audio)), audio).astype(np.float32)


def drain(blocks: queue.Queue) -> None:
    """Throw away audio recorded so far (e.g. while she was talking)."""
    while not blocks.empty():
        blocks.get_nowait()


class Transcriber:
    """Turns recorded speech into text with Whisper, on your own computer."""

    def __init__(self, settings: ListenSettings):
        self.s = settings
        self._model = None

    def load(self) -> None:
        """Load (and the first time, download) the model. Takes a few seconds."""
        if self._model is None:
            from faster_whisper import WhisperModel

            started = time.monotonic()
            self._model = WhisperModel(self.s.model, device="cpu", compute_type="int8")
            print(f"(Speech recognition ready after {time.monotonic() - started:.1f} s)")

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        self.load()
        segments, _ = self._model.transcribe(
            to_whisper_rate(audio, sample_rate),
            language=self.s.language or None,  # "" = work out the language itself
            beam_size=1,  # fastest; plenty for short questions
            vad_filter=True,  # ignore stretches without speech
        )
        return " ".join(s.text.strip() for s in segments).strip()
