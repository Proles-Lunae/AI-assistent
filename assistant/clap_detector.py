"""Listen to the microphone and detect two claps in a row."""

from __future__ import annotations

import queue
import time
from collections import deque
from typing import Callable

import numpy as np

from .config import ClapSettings

# Below this, the microphone is sending (almost) pure silence.
SILENT = 0.0005


class DoubleClapDetector:
    """Spots a double clap in a stream of audio blocks.

    A block counts as a clap when its loudest moment (peak):
      * reaches ``threshold`` (0 = silence, 1 = maximum),
      * is ``noise_ratio`` times louder than the usual background peaks, and
      * appeared suddenly: ``onset_ratio`` times louder than a moment before.
        Claps are sudden; speech and music build up, so this filters them out.

    Two claps between ``min_gap`` and ``max_gap`` seconds apart make a double
    clap. ``process_block`` holds all the logic and needs no microphone, so it
    can be tested with generated audio.
    """

    # One clap can spill over two audio blocks; don't count it twice.
    REFRACTORY = 0.08

    def __init__(self, settings: ClapSettings):
        self.s = settings
        self.background = 0.01  # Running estimate of background peak loudness.
        self.recent = deque([0.0, 0.0], maxlen=2)  # Peaks of the last two blocks.
        self.last_clap: float | None = None
        self.quiet_until = 0.0
        self.last_peak = 0.0

    def is_clap(self, block: np.ndarray) -> bool:
        peak = float(np.max(np.abs(block))) if len(block) else 0.0
        self.last_peak = peak
        before = self.recent[0]  # ~50 ms ago, before a clap would have started
        self.recent.append(peak)
        loud = peak >= self.s.threshold
        above_background = peak >= self.background * self.s.noise_ratio
        sudden = peak >= max(before, SILENT) * self.s.onset_ratio
        if not loud:
            # Learn the background level only from ordinary (non-clap) sound.
            self.background = 0.97 * self.background + 0.03 * max(peak, 0.002)
        return loud and above_background and sudden

    def process_block(self, block: np.ndarray, now: float) -> str | None:
        """Feed one block of audio (floats from -1 to 1).

        Returns "double" on a double clap, "single" on a first clap, else None.
        """
        clap = self.is_clap(block)
        if now < self.quiet_until or not clap:
            return None
        if self.last_clap is not None:
            gap = now - self.last_clap
            if gap < self.REFRACTORY:
                return None
            if self.s.min_gap <= gap <= self.s.max_gap:
                self.last_clap = None
                self.quiet_until = now + self.s.cooldown
                return "double"
        self.last_clap = now
        return "single"

    def listen(self, on_double_clap: Callable[[], None]) -> None:
        """Listen to the microphone forever, calling back on each double clap."""
        import sounddevice as sd

        blocks: queue.Queue[np.ndarray] = queue.Queue()
        device = input_device(self.s)
        print(f"Using microphone: {device_name(device)}")

        def callback(indata, frames, time_info, status):  # runs on the audio thread
            blocks.put(indata[:, 0].copy())

        started = time.monotonic()
        loudest = 0.0
        warned = False
        with sd.InputStream(
            device=device,
            samplerate=self.s.sample_rate,
            blocksize=self.s.block_size,
            channels=1,
            dtype="float32",
            callback=callback,
        ):
            while True:
                block = blocks.get()
                result = self.process_block(block, time.monotonic())
                loudest = max(loudest, self.last_peak)
                if not warned and time.monotonic() - started > 4:
                    warned = True
                    if loudest < SILENT:
                        print(SILENCE_HELP)
                if result == "single":
                    print(f"  clap heard (loudness {self.last_peak:.2f}), clap once more...")
                elif result == "double":
                    on_double_clap()
                    # Drop audio recorded while we were talking, including our own voice.
                    while not blocks.empty():
                        blocks.get_nowait()
                    self.quiet_until = time.monotonic() + self.s.cooldown
                    self.recent.extend([0.0, 0.0])


SILENCE_HELP = """
  The microphone is sending complete silence. Check that:
   * Windows lets apps use it: Settings > Privacy & security > Microphone >
     turn on "Microphone access" and "Let desktop apps access your microphone".
   * The microphone isn't muted and is the default recording device
     (or set 'device' under [clap] in config.toml; see: python -m assistant --devices).
"""


def input_device(settings: ClapSettings, devices=None, default_hostapi=None):
    """The device from config.toml: '' = system default, a number, or part of a name.

    Windows lists each microphone several times (once per audio system: MME,
    DirectSound, WASAPI...), so a name usually matches more than one entry.
    Pick the one on the default audio system, else the first match.
    """
    device = str(settings.device).strip()
    if not device:
        return None
    if device.isdigit():
        return int(device)
    if devices is None:
        import sounddevice as sd

        devices = sd.query_devices()
        default_hostapi = sd.default.hostapi
    wanted = device.lower()
    matches = [
        i
        for i, d in enumerate(devices)
        if d["max_input_channels"] > 0 and wanted in d["name"].lower()
    ]
    if not matches:
        raise ValueError(
            f"No microphone matches '{device}'. See the list with: python -m assistant --devices"
        )
    for i in matches:
        if devices[i].get("hostapi") == default_hostapi:
            return i
    return matches[0]


def device_name(device) -> str:
    import sounddevice as sd

    try:
        return sd.query_devices(device, kind="input")["name"]
    except Exception as exc:
        return f"{device} ({exc})"


def list_devices() -> None:
    import sounddevice as sd

    print("Microphones (use the number or part of the name as 'device' under [clap]):\n")
    default = sd.default.device[0]
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            mark = "  <- default" if i == default else ""
            print(f"  {i:3d}: {d['name']}{mark}")


def show_levels(settings: ClapSettings, seconds: float = 20.0) -> None:
    """Show microphone loudness and what the detector makes of it."""
    import sounddevice as sd

    detector = DoubleClapDetector(settings)
    blocks: queue.Queue[np.ndarray] = queue.Queue()
    device = input_device(settings)
    print(f"Using microphone: {device_name(device)}")
    print(f"Showing loudness for {seconds:.0f} seconds. Stay quiet a moment, then clap.")
    print(f"A clap must reach {settings.threshold} (the | mark).\n")

    def callback(indata, frames, time_info, status):
        blocks.put(indata[:, 0].copy())

    width = 50
    mark = min(int(settings.threshold * width), width - 1)
    loudest = 0.0
    window_peak, window_note, count = 0.0, "", 0
    with sd.InputStream(
        device=device,
        samplerate=settings.sample_rate,
        blocksize=settings.block_size,
        channels=1,
        dtype="float32",
        callback=callback,
    ):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            block = blocks.get()
            result = detector.process_block(block, time.monotonic())
            window_peak = max(window_peak, detector.last_peak)
            loudest = max(loudest, detector.last_peak)
            if result == "single":
                window_note = window_note or "  CLAP"
            elif result == "double":
                window_note = "  DOUBLE CLAP -> would wake up!"
            count += 1
            if count == 4:  # print about 10 lines a second
                bar = list("#" * min(int(window_peak * width), width) + " " * width)[:width]
                bar[mark] = "|"
                print(f"{window_peak:5.2f} {''.join(bar)}{window_note}")
                window_peak, window_note, count = 0.0, "", 0
    print(f"\nLoudest sound: {loudest:.2f}")
    if loudest < SILENT:
        print(SILENCE_HELP)
    elif loudest < settings.threshold:
        print(
            f"Nothing reached the clap threshold ({settings.threshold}). Set 'threshold' "
            f"under [clap] in config.toml to about {max(loudest * 0.6, 0.02):.2f}."
        )
