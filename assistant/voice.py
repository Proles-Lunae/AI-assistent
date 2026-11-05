"""Speak text out loud in a British female voice.

Uses Microsoft's free neural voices through ``edge-tts`` (needs internet).
If that fails, falls back to the voices built into your computer via
``pyttsx3`` (offline, picks a British female voice if it can find one).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import VoiceSettings

SAMPLE_RATE = 24000
# Words that mark an offline voice as British, or as female.
BRITISH_HINTS = ("en_gb", "en-gb", "united kingdom", "british")
FEMALE_HINTS = ("hazel", "susan", "kate", "serena", "libby", "sonia", "female")


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

    def play(self, speech: Speech, wait: bool = True) -> None:
        """Speak ``speech``. With ``wait=False`` it returns while still talking
        (call ``finish()`` to wait), so the next sentence can be made meanwhile."""
        print(f"Assistant: {speech.text}")
        if speech.samples is not None:
            try:
                import sounddevice as sd

                sd.play(speech.samples, SAMPLE_RATE)
                if wait:
                    sd.wait()
                return
            except Exception as exc:  # no audio device...
                print(f"(Couldn't play audio: {exc}. Trying the offline voice.)")
        self._say_offline(speech.text)

    def finish(self) -> None:
        """Wait until the current audio has finished playing."""
        try:
            import sounddevice as sd

            sd.wait()
        except Exception:
            pass

    def _render(self, text: str):
        """Make the neural-voice audio (MP3) and decode it, ready for the speakers."""
        import asyncio

        import edge_tts
        import miniaudio
        import numpy as np

        async def download() -> bytes:
            communicate = edge_tts.Communicate(text, self.s.voice, rate=self.s.rate)
            chunks = [c["data"] async for c in communicate.stream() if c["type"] == "audio"]
            return b"".join(chunks)

        mp3 = asyncio.run(download())
        if not mp3:
            raise RuntimeError("the voice service returned no audio")
        decoded = miniaudio.decode(
            mp3, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=SAMPLE_RATE
        )
        return trim_silence(np.frombuffer(decoded.samples, dtype=np.int16))

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


def trim_silence(samples, lead: float = 0.02, tail: float = 0.15, level: int = 300):
    """Cut the silence the voice service adds around speech, keeping a short
    natural pause at the end, so two recordings played back to back sound
    like one sentence."""
    import numpy as np

    loud = np.flatnonzero(np.abs(samples) > level)
    if not len(loud):
        return samples
    start = max(0, loud[0] - int(lead * SAMPLE_RATE))
    end = min(len(samples), loud[-1] + int(tail * SAMPLE_RATE))
    return samples[start:end]


def pick_british_female(voices):
    """Choose the best match for a British female voice from pyttsx3's list.

    British and female beats British only, which beats female only; None if neither.
    """

    def score(v) -> tuple[bool, bool]:
        langs = " ".join(
            l.decode(errors="ignore") if isinstance(l, bytes) else str(l)
            for l in (getattr(v, "languages", None) or [])
        )
        d = f"{v.id} {v.name} {langs} {getattr(v, 'gender', '')}".lower()
        return any(k in d for k in BRITISH_HINTS), any(k in d for k in FEMALE_HINTS)

    best = max(voices, key=score, default=None)  # the first of the best
    return best if best is not None and any(score(best)) else None
