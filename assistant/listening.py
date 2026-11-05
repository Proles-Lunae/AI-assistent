"""Hear what you say: record one question from the microphone and turn it into text.

Recording stops by itself once you've been quiet for a moment. The speech is
turned into text on your own PC with Whisper (the faster-whisper package), so
your voice isn't sent anywhere. The first time, Whisper downloads its model
(about 460 MB for "small").
"""

from __future__ import annotations

import queue
import time

import numpy as np

from .config import ListenSettings

WHISPER_RATE = 16000  # Whisper expects 16 kHz audio
LEAD_IN = 0.3  # seconds kept from just before you started, so no syllable is lost


class MicrophoneStopped(RuntimeError):
    """The microphone stopped sending audio (unplugged, or taken by another app)."""


def record_question(blocks: queue.Queue, sample_rate: int, settings: ListenSettings):
    """Record from ``blocks`` until you stop talking.

    Waits up to ``wait_seconds`` for you to start, then stops after
    ``silence_seconds`` of quiet (or ``max_seconds`` in total). Returns the
    audio as one array, or None if you didn't say anything in that time.
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
            raise MicrophoneStopped("no sound from the microphone for a second") from None
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
                keep = max(1, round(LEAD_IN / block_seconds))
                heard = heard[-keep:] + [block]  # keep a moment before you start talking
            continue
        heard.append(block)
        quiet_for = 0.0 if loud else quiet_for + block_seconds
        if quiet_for >= settings.silence_seconds or len(heard) * block_seconds >= settings.max_seconds:
            return np.concatenate(heard)


def to_whisper_rate(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Resample the microphone audio to the 16 kHz Whisper expects.

    High pitches are filtered out first; without that they'd fold back into
    the speech as distortion and make it harder to recognise.
    """
    audio = audio.astype(np.float32)
    if sample_rate == WHISPER_RATE:
        return audio
    if sample_rate > WHISPER_RATE:
        audio = np.convolve(audio, lowpass(0.9 * WHISPER_RATE / 2, sample_rate), mode="same")
    length = int(len(audio) * WHISPER_RATE / sample_rate)
    positions = np.linspace(0, len(audio) - 1, length)
    return np.interp(positions, np.arange(len(audio)), audio).astype(np.float32)


def lowpass(cutoff: float, sample_rate: int, taps: int = 101) -> np.ndarray:
    """A filter that keeps sounds below ``cutoff`` Hz (windowed sinc)."""
    n = np.arange(taps) - (taps - 1) / 2
    kernel = np.sinc(2 * cutoff / sample_rate * n) * np.hamming(taps)
    return (kernel / kernel.sum()).astype(np.float32)


def louder(audio: np.ndarray, target: float = 0.9, most: float = 20.0) -> np.ndarray:
    """Bring quiet speech (e.g. from a dynamic microphone) up to a good level."""
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak <= 0:
        return audio
    return audio * min(target / peak, most)


def drain(blocks: queue.Queue) -> None:
    """Throw away audio recorded so far (e.g. while she was talking)."""
    while not blocks.empty():
        blocks.get_nowait()


def quiet_model_download() -> None:
    """Hide harmless warnings from the model download (huggingface_hub) on Windows:
    that it can't use symlinks (it stores a plain copy instead) and that it's
    downloading without an account (none is needed)."""
    import logging
    import os
    import warnings

    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")  # read when the library loads
    warnings.filterwarnings("ignore", module="huggingface_hub")
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)


class Transcriber:
    """Turns recorded speech into text with Whisper, on your own computer."""

    def __init__(self, settings: ListenSettings, language: str = "en", prompt: str = ""):
        self.s = settings
        self.default_language = language  # [user] language, used when [listen] has none
        self.prompt = prompt  # an example sentence, which helps recognition
        self._model = None

    def language(self) -> str | None:
        """The language code for Whisper, or None to let it detect the language."""
        chosen = self.s.language.strip().lower() or self.default_language
        return None if chosen == "auto" else chosen[:2]

    def load(self) -> None:
        """Load (and the first time, download) the model. Takes a few seconds."""
        if self._model is None:
            quiet_model_download()
            from faster_whisper import WhisperModel

            print("(Loading speech recognition; the first time it downloads about 140 MB...)")
            started = time.monotonic()
            self._model = WhisperModel(self.s.model, device="cpu", compute_type="int8")
            print(f"(Speech recognition ready after {time.monotonic() - started:.1f} s)")

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        self.load()
        segments, _ = self._model.transcribe(
            louder(to_whisper_rate(audio, sample_rate)),
            language=self.language(),
            beam_size=5,  # weigh up several readings: more accurate than the fastest
            vad_filter=True,  # ignore stretches without speech
            initial_prompt=self.prompt or None,
            condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments).strip()
