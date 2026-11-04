"""Listen to the microphone and detect two claps in a row."""

from __future__ import annotations

import time
from typing import Callable

import numpy as np

from .config import ClapSettings


class DoubleClapDetector:
    """Spots a double clap in a stream of audio blocks.

    A clap is a short, sharp sound: much louder than the background and over
    almost instantly. Each audio block is checked for that, and two claps with
    the right gap between them count as a double clap.

    ``process_block`` holds all the logic and needs no microphone, so it can be
    tested with generated audio.
    """

    # A single clap can spill over two audio blocks; don't count it twice.
    REFRACTORY = 0.08

    def __init__(self, settings: ClapSettings):
        self.s = settings
        self.background = 0.01  # Running estimate of background loudness (RMS).
        self.last_clap: float | None = None
        self.quiet_until = 0.0

    def is_clap(self, block: np.ndarray) -> bool:
        peak = float(np.max(np.abs(block)))
        rms = float(np.sqrt(np.mean(np.square(block))))
        loud = peak >= self.s.threshold
        sharp = rms >= self.background * self.s.noise_ratio
        if not loud:
            # Only learn the background level from non-clap sound.
            self.background = 0.95 * self.background + 0.05 * max(rms, 1e-4)
        return loud and sharp

    def process_block(self, block: np.ndarray, now: float) -> bool:
        """Feed one block of audio (floats from -1 to 1). True on a double clap."""
        clap = self.is_clap(block)
        if now < self.quiet_until or not clap:
            return False
        if self.last_clap is not None:
            gap = now - self.last_clap
            if gap < self.REFRACTORY:
                return False
            if self.s.min_gap <= gap <= self.s.max_gap:
                self.last_clap = None
                self.quiet_until = now + self.s.cooldown
                return True
        self.last_clap = now
        return False

    def listen(self, on_double_clap: Callable[[], None]) -> None:
        """Listen to the default microphone forever, calling back on each double clap."""
        import queue

        import sounddevice as sd

        blocks: queue.Queue[np.ndarray] = queue.Queue()

        def callback(indata, frames, time_info, status):  # runs on the audio thread
            blocks.put(indata[:, 0].copy())

        with sd.InputStream(
            samplerate=self.s.sample_rate,
            blocksize=self.s.block_size,
            channels=1,
            dtype="float32",
            callback=callback,
        ):
            while True:
                block = blocks.get()
                if self.process_block(block, time.monotonic()):
                    on_double_clap()
                    # Drop audio recorded while we were talking, including our own voice.
                    while not blocks.empty():
                        blocks.get_nowait()
                    self.quiet_until = time.monotonic() + self.s.cooldown


def show_levels(settings: ClapSettings, seconds: float = 15.0) -> None:
    """Print microphone loudness so you can pick a good clap threshold."""
    import sounddevice as sd

    print(f"Showing microphone levels for {seconds:.0f} seconds. Try clapping.")
    print(f"Current threshold: {settings.threshold}\n")

    def callback(indata, frames, time_info, status):
        peak = float(np.max(np.abs(indata)))
        bar = "#" * int(peak * 50)
        mark = "  <- clap?" if peak >= settings.threshold else ""
        print(f"{peak:5.2f} {bar}{mark}")

    with sd.InputStream(
        samplerate=settings.sample_rate,
        blocksize=settings.block_size * 4,
        channels=1,
        dtype="float32",
        callback=callback,
    ):
        time.sleep(seconds)
