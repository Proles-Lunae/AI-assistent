"""Detect two claps in a row in a stream of audio blocks.

This is only the logic; ``microphone.py`` feeds it the sound. That keeps it
testable with generated audio, without a microphone.
"""

from __future__ import annotations

from collections import deque

from .config import ClapSettings

SILENT = 0.0005  # Below this, the microphone is sending (almost) pure silence.


class DoubleClapDetector:
    """Spots a double clap in a stream of audio blocks.

    A block counts as a clap when its loudest moment (peak):
      * reaches ``threshold`` (0 = silence, 1 = maximum),
      * is ``noise_ratio`` times louder than the usual background peaks, and
      * appeared suddenly: ``onset_ratio`` times louder than a moment before.
        Claps are sudden; speech and music build up, so this filters them out.

    Two claps between ``min_gap`` and ``max_gap`` seconds apart make a double
    clap. After one, everything is ignored for ``cooldown`` seconds.
    """

    REFRACTORY = 0.08  # One clap can spill over two audio blocks; don't count it twice.

    def __init__(self, settings: ClapSettings):
        self.s = settings
        self.background = 0.01  # Running estimate of background peak loudness.
        self.recent = deque([0.0, 0.0], maxlen=2)  # Peaks of the last two blocks.
        self.last_clap: float | None = None
        self.quiet_until = 0.0
        self.last_peak = 0.0

    def process_block(self, block, now: float) -> str | None:
        """Feed one block of audio (a numpy array of floats from -1 to 1).

        Returns "double" on a double clap, "single" on a first clap, else None.
        """
        peak = self.last_peak = float(abs(block).max()) if len(block) else 0.0
        before = self.recent[0]  # ~50 ms ago, before a clap would have started
        self.recent.append(peak)
        if peak < self.s.threshold:
            # Learn the background level only from ordinary (non-clap) sound.
            self.background = 0.97 * self.background + 0.03 * max(peak, 0.002)
            return None
        is_clap = (peak >= self.background * self.s.noise_ratio
                   and peak >= max(before, SILENT) * self.s.onset_ratio)
        if now < self.quiet_until or not is_clap:
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

    def restart_cooldown(self, now: float) -> None:
        """Ignore sound for ``cooldown`` seconds from ``now``, e.g. after the assistant spoke."""
        self.quiet_until = now + self.s.cooldown
        self.recent.extend([0.0, 0.0])
