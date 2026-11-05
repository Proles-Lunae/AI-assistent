"""The microphone: choosing it, reading its sound, and showing how loud it is."""

from __future__ import annotations

import queue
import time
from contextlib import contextmanager
from typing import Callable

from .clap_detector import SILENT, DoubleClapDetector
from .config import ClapSettings, ConfigError

SILENCE_HELP = """
  The microphone is sending complete silence. Check that:
   * Windows lets apps use it: Settings > Privacy & security > Microphone >
     turn on "Microphone access" and "Let desktop apps access your microphone".
   * The microphone isn't muted and is the default recording device
     (or set 'device' under [clap] in config.toml; see: python -m assistant --devices).
"""


def listen(settings: ClapSettings, on_double_clap: Callable[[queue.Queue], None],
           on_clap: Callable[[], None] | None = None) -> None:
    """Listen to the microphone forever, calling ``on_double_clap`` on each double clap.

    It's given the queue of microphone audio, so it can listen to you too.
    """
    detector = DoubleClapDetector(settings)
    with recording(settings, choose_microphone(settings)) as blocks:
        started, loudest, warned = time.monotonic(), 0.0, False
        while True:
            result = detector.process_block(blocks.get(), time.monotonic())
            loudest = max(loudest, detector.last_peak)
            if not warned and time.monotonic() - started > 4:
                warned = True
                if loudest < SILENT:
                    print(SILENCE_HELP)
            if result == "single":
                print(f"  clap heard (loudness {detector.last_peak:.2f}), clap once more...")
                if on_clap is not None:
                    on_clap()
            elif result == "double":
                on_double_clap(blocks)
                # Drop audio recorded while we were talking, including our own voice.
                while not blocks.empty():
                    blocks.get_nowait()
                detector.restart_cooldown(time.monotonic())


def show_levels(settings: ClapSettings, seconds: float = 20.0) -> None:
    """Show microphone loudness and what the detector makes of it (--levels)."""
    detector = DoubleClapDetector(settings)
    device = choose_microphone(settings)
    print(f"Showing loudness for {seconds:.0f} seconds. Stay quiet a moment, then clap.")
    print(f"A clap must reach {settings.threshold} (the | mark).\n")
    width = 50
    mark = min(int(settings.threshold * width), width - 1)
    loudest, window_peak, note, count = 0.0, 0.0, "", 0
    with recording(settings, device) as blocks:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            result = detector.process_block(blocks.get(), time.monotonic())
            window_peak = max(window_peak, detector.last_peak)
            loudest = max(loudest, detector.last_peak)
            if result == "single":
                note = note or "  CLAP"
            elif result == "double":
                note = "  DOUBLE CLAP -> would wake up!"
            count += 1
            if count % 4 == 0:  # print about 10 lines a second
                bar = ("#" * int(window_peak * width)).ljust(width)[:width]
                print(f"{window_peak:5.2f} {bar[:mark]}|{bar[mark + 1:]}{note}")
                window_peak, note = 0.0, ""
    print(f"\nLoudest sound: {loudest:.2f}")
    if loudest < SILENT:
        print(SILENCE_HELP)
    elif loudest < settings.threshold:
        print(
            f"Nothing reached the clap threshold ({settings.threshold}). Set 'threshold' "
            f"under [clap] in config.toml to about {max(loudest * 0.6, 0.02):.2f}."
        )


def list_devices() -> None:
    """Print the microphones, with their numbers (--devices)."""
    import sounddevice as sd

    print("Microphones (use the number or part of the name as 'device' under [clap]):\n")
    default = sd.default.device[0]
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            mark = "  <- default" if i == default else ""
            print(f"  {i:3d}: {d['name']}{mark}")


def choose_microphone(settings: ClapSettings) -> int | None:
    """The microphone to record from (None = the default one); says which it is."""
    device = input_device(settings)
    print(f"Using microphone: {device_name(device)}")
    return device


@contextmanager
def recording(settings: ClapSettings, device: int | None):
    """Record from ``device``; gives a queue that fills with audio blocks (numpy arrays)."""
    import sounddevice as sd

    blocks = queue.Queue()

    def callback(indata, frames, time_info, status):  # runs on the audio thread
        blocks.put(indata[:, 0].copy())

    with sd.InputStream(device=device, samplerate=settings.sample_rate, channels=1,
                        blocksize=settings.block_size, dtype="float32", callback=callback):
        yield blocks


def input_device(settings: ClapSettings, devices=None, default_hostapi=None) -> int | None:
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

        devices, default_hostapi = sd.query_devices(), sd.default.hostapi
    matches = [i for i, d in enumerate(devices)
               if d["max_input_channels"] > 0 and device.lower() in d["name"].lower()]
    if not matches:
        # A settings mistake: main() prints it as a plain message, without a traceback.
        raise ConfigError(
            f"No microphone matches '{device}'. See the list with: python -m assistant --devices"
        )
    return next((i for i in matches if devices[i].get("hostapi") == default_hostapi), matches[0])


def device_name(device: int | None) -> str:
    import sounddevice as sd

    try:
        return sd.query_devices(device, kind="input")["name"]
    except Exception as exc:
        return f"{device} ({exc})"
