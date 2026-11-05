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
# How to recognise a fitting offline (pyttsx3) voice, by language.
LANGUAGE_HINTS = {
    "en": ("en_gb", "en-gb", "united kingdom", "british"),
    "de": ("de_de", "de-de", "german", "deutsch"),
}
BRITISH_HINTS = LANGUAGE_HINTS["en"]
FEMALE_HINTS = ("hazel", "susan", "kate", "serena", "libby", "sonia", "katja", "hedda",
                "amala", "anna", "petra", "marlene", "female")


def choose_voice(setting: str, language: str, default_voice: str) -> str:
    """The neural voice to use: the one set in config.toml, unless it's for a
    different language than she speaks (e.g. the old British default with
    German), in which case the usual voice for her language."""
    setting = setting.strip()
    if not setting:
        return default_voice
    if not setting.lower().startswith(language.lower()[:2] + "-"):
        print(f"(The voice '{setting}' is for another language; using {default_voice}. "
              f"Set voice under [voice] to a '{language[:2]}-' voice to choose another.)")
        return default_voice
    return setting


@dataclass
class Speech:
    """Text that's ready to be played straight away.

    ``samples`` holds the finished audio. It's None when the online voice
    couldn't be reached; the offline voice then speaks the text at play time.
    """

    text: str
    samples: Any = None


class Speaker:
    def __init__(self, settings: VoiceSettings, language: str = "en", default_voice: str = ""):
        self.s = settings
        self.language = language
        self.voice = choose_voice(settings.voice, language, default_voice or "en-GB-SoniaNeural")
        self.on_speak = lambda text: None  # told each sentence as she starts saying it

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
        self.on_speak(speech.text)
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

    def beep(self) -> None:
        """A short soft tone that means "I'm listening"."""
        try:
            import numpy as np
            import sounddevice as sd

            t = np.arange(int(0.15 * SAMPLE_RATE)) / SAMPLE_RATE
            fade = np.minimum(1, np.minimum(t, t[-1] - t) / 0.02)  # no clicks
            tone = (np.sin(2 * np.pi * 880 * t) * fade * 6000).astype(np.int16)
            sd.play(tone, SAMPLE_RATE)
            sd.wait()
        except Exception:
            pass  # no audio device: the "Listening..." message still shows

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
            communicate = edge_tts.Communicate(text, self.voice, rate=self.s.rate)
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
        voice = pick_british_female(engine.getProperty("voices"), self.language)
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


def pick_british_female(voices, language: str = "en"):
    """Choose the best offline voice from pyttsx3's list: British female for
    English, German female for German.

    Right language and female beats language only, which beats female only;
    None if neither.
    """
    hints = LANGUAGE_HINTS.get(language[:2], BRITISH_HINTS)

    def score(v) -> tuple[bool, bool]:
        langs = " ".join(
            l.decode(errors="ignore") if isinstance(l, bytes) else str(l)
            for l in (getattr(v, "languages", None) or [])
        )
        d = f"{v.id} {v.name} {langs} {getattr(v, 'gender', '')}".lower()
        return any(k in d for k in hints), any(k in d for k in FEMALE_HINTS)

    best = max(voices, key=score, default=None)  # the first of the best
    return best if best is not None and any(score(best)) else None
