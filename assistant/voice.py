"""Speak text out loud in a British female voice.

Uses Microsoft's free neural voices through ``edge-tts`` (needs internet).
If that fails, falls back to the voices built into your computer via
``pyttsx3`` (offline, picks a British female voice if it can find one).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from .config import VoiceSettings

SAMPLE_RATE = 24000


@dataclass
class Speech:
    """Text that's ready to be played straight away.

    ``samples`` holds the finished audio. It's None when the online voice
    couldn't be reached; the offline voice then speaks the text at play time.
    """

    text: str
    samples: Any = None


class Speaker:
    def __init__(self, settings: VoiceSettings):
        self.s = settings

    def say(self, text: str) -> None:
        self.play(self.prepare(text))

    def prepare(self, text: str) -> Speech:
        """Do the slow part (making the audio) ahead of time."""
        try:
            return Speech(text, self._render(text))
        except Exception as exc:  # network down, voice service changed...
            print(f"(Online voice failed: {exc}. Will use the offline voice.)")
            return Speech(text)

    def play(self, speech: Speech) -> None:
        print(f"Assistant: {speech.text}")
        if speech.samples is not None:
            try:
                import sounddevice as sd

                sd.play(speech.samples, SAMPLE_RATE)
                sd.wait()
                return
            except Exception as exc:  # no audio device...
                print(f"(Couldn't play audio: {exc}. Trying the offline voice.)")
        self._say_offline(speech.text)

    def synthesize(self, text: str) -> bytes:
        """Turn text into MP3 bytes with the neural voice."""
        import edge_tts

        async def run() -> bytes:
            communicate = edge_tts.Communicate(text, self.s.voice, rate=self.s.rate)
            audio = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio.extend(chunk["data"])
            return bytes(audio)

        audio = asyncio.run(run())
        if not audio:
            raise RuntimeError("the voice service returned no audio")
        return audio

    def _render(self, text: str):
        """Make the neural-voice audio and decode it, ready for the speakers."""
        import miniaudio
        import numpy as np

        mp3 = self.synthesize(text)
        decoded = miniaudio.decode(
            mp3,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=1,
            sample_rate=SAMPLE_RATE,
        )
        return np.frombuffer(decoded.samples, dtype=np.int16)

    def _say_offline(self, text: str) -> None:
        try:
            import pyttsx3
        except ImportError:
            print("(No offline voice installed. Run: pip install pyttsx3)")
            return
        engine = pyttsx3.init()
        voice = pick_british_female(engine.getProperty("voices"))
        if voice is not None:
            engine.setProperty("voice", voice.id)
        engine.say(text)
        engine.runAndWait()


def pick_british_female(voices):
    """Choose the best match for a British female voice from pyttsx3's list."""
    female_names = ("hazel", "susan", "kate", "serena", "libby", "sonia", "female")

    def describe(v) -> str:
        langs = " ".join(
            l.decode(errors="ignore") if isinstance(l, bytes) else str(l)
            for l in (getattr(v, "languages", None) or [])
        )
        return f"{v.id} {v.name} {langs} {getattr(v, 'gender', '')}".lower()

    def is_british(d: str) -> bool:
        return any(k in d for k in ("en_gb", "en-gb", "united kingdom", "british"))

    def is_female(d: str) -> bool:
        return any(k in d for k in female_names)

    described = [(v, describe(v)) for v in voices]
    for test in (lambda d: is_british(d) and is_female(d), is_british, is_female):
        for v, d in described:
            if test(d):
                return v
    return None
