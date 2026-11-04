"""Keep the weather briefing ready ahead of time, so it plays the moment you clap.

Making a briefing is slow: fetching the weather, asking Claude, and turning
the text into speech add up to several seconds. A background thread makes one
briefing per time frame (morning, afternoon, evening), and every clap in that
frame reuses it.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .brain import frame_start
from .voice import Speech


@dataclass
class Briefing:
    speech: Speech
    frame: datetime  # start of the time frame it was made for
    made_at: float  # time.monotonic() when it was made
    complete: bool  # False if the weather couldn't be fetched


def current_frame() -> datetime:
    return frame_start(datetime.now())


class BriefingCache:
    """Holds the briefing for the current time frame, made in the background.

    A new briefing is made when a new time frame starts. One made without
    weather (service unreachable) is retried after ``incomplete_max_age``
    seconds.
    """

    def __init__(
        self,
        build: Callable[[], Briefing],
        incomplete_max_age: float = 120.0,
        retry_delay: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        frame: Callable[[], datetime] = current_frame,
    ):
        self.build = build
        self.incomplete_max_age = incomplete_max_age
        self.retry_delay = retry_delay
        self.clock = clock
        self.frame = frame
        self._cond = threading.Condition()
        self._ready: Briefing | None = None
        self._stopped = False
        self._thread: threading.Thread | None = None

    def is_fresh(self, briefing: Briefing) -> bool:
        if briefing.frame != self.frame():
            return False
        return briefing.complete or self.clock() - briefing.made_at < self.incomplete_max_age

    def start(self) -> None:
        self._thread = threading.Thread(target=self._worker, name="briefing", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify_all()

    def take(self, timeout: float = 0.0) -> Briefing | None:
        """Return this time frame's briefing, waiting up to ``timeout`` seconds.

        Returns None if nothing fresh is ready in time.
        """
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                if self._ready is not None:
                    if self.is_fresh(self._ready):
                        return self._ready
                    self._ready = None
                    self._cond.notify_all()  # wake the worker to make a new one
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._stopped:
                    return None
                self._cond.wait(timeout=remaining)

    def _worker(self) -> None:
        while True:
            with self._cond:
                # Sleep while the briefing is still good; check again every
                # 30 seconds whether a new time frame has started.
                while not self._stopped and self._ready and self.is_fresh(self._ready):
                    self._cond.wait(timeout=30)
                if self._stopped:
                    return
            try:
                briefing = self.build()
            except Exception as exc:
                print(f"(Couldn't prepare the weather briefing: {exc})")
                briefing = None
            with self._cond:
                if briefing is not None:
                    self._ready = briefing
                    self._cond.notify_all()
                elif not self._stopped:
                    self._cond.wait(timeout=self.retry_delay)
