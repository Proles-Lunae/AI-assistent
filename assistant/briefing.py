"""Keep greeting + forecast ready ahead of time, so it plays the moment you clap.

Making a briefing is slow: fetching the weather, asking Claude, and turning
the text into speech add up to several seconds. A background thread makes one
briefing (greeting and forecast as a single recording) per time frame:
morning, afternoon and evening. The next frame's briefing is made shortly
before that frame starts, so there's no wait when the frame changes.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .brain import frame_end, frame_start
from .voice import Speech


@dataclass
class Briefing:
    speech: Speech  # greeting and forecast together, ready to play
    weather_text: str  # the forecast on its own
    frame: datetime  # start of the time frame it's for
    made_at: float  # time.monotonic() when it was made
    complete: bool  # False if it's a stand-in (quick version, or no weather): remade soon


class BriefingCache:
    """Holds the briefings for the current and the next time frame.

    ``build(frame_start)`` makes one briefing. One made without weather
    (service unreachable) is remade after ``incomplete_max_age`` seconds, but
    keeps being played until the new one is ready, so a clap never waits.
    """

    def __init__(
        self,
        build: Callable[[datetime], Briefing],
        lead: float = 30 * 60,
        incomplete_max_age: float = 120.0,
        retry_delay: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = datetime.now,
    ):
        self.build = build
        self.lead = lead  # make the next frame's briefing this many seconds early
        self.incomplete_max_age = incomplete_max_age
        self.retry_delay = retry_delay
        self.clock = clock
        self.now = now
        self._cond = threading.Condition()
        self._ready: dict[datetime, Briefing] = {}
        self._stopped = False
        self._thread: threading.Thread | None = None

    def usable(self, briefing: Briefing) -> bool:
        return briefing.complete or self.clock() - briefing.made_at < self.incomplete_max_age

    def wanted_frames(self) -> list[datetime]:
        """The current frame, plus the next one if it starts soon."""
        now = self.now()
        current = frame_start(now)
        upcoming = frame_end(current)
        if (upcoming - now).total_seconds() <= self.lead:
            return [current, upcoming]
        return [current]

    def next_to_build(self) -> datetime | None:
        frames = self.wanted_frames()
        for old in [f for f in self._ready if f < frames[0]]:
            del self._ready[old]  # frames that are over
        for frame in frames:
            briefing = self._ready.get(frame)
            if briefing is None or not self.usable(briefing):
                return frame
        return None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._worker, name="briefing", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify_all()

    def offer(self, briefing: Briefing) -> None:
        """Keep a stand-in briefing for its frame, unless a better one is there."""
        with self._cond:
            self._ready.setdefault(briefing.frame, briefing)

    def take(self, timeout: float = 0.0) -> Briefing | None:
        """The current frame's briefing, waiting up to ``timeout`` seconds for it."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                briefing = self._ready.get(frame_start(self.now()))
                if briefing is not None:
                    return briefing
                self._cond.notify_all()  # make sure the worker is on it
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._stopped:
                    return None
                self._cond.wait(timeout=remaining)

    def _worker(self) -> None:
        while True:
            with self._cond:
                # Sleep until something needs making; check every 30 seconds
                # whether the next frame is getting close.
                while not self._stopped and (frame := self.next_to_build()) is None:
                    self._cond.wait(timeout=30)
                if self._stopped:
                    return
            try:
                briefing = self.build(frame)
            except Exception as exc:
                print(f"(Couldn't prepare the {frame:%H:%M} greeting: {exc})")
                briefing = None
            with self._cond:
                if briefing is not None:
                    self._ready[frame] = briefing
                    self._cond.notify_all()
                elif not self._stopped:
                    self._cond.wait(timeout=self.retry_delay)
