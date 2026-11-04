"""Keep the next greeting ready ahead of time, so it plays the moment you clap.

Making a greeting is slow: fetching the weather, asking Claude, and turning
the text into speech add up to several seconds. A background thread does all
that while the assistant waits for claps, and keeps the result fresh.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .brain import time_of_day
from .voice import Speech


@dataclass
class Briefing:
    speech: Speech
    made_at: float  # time.monotonic() when it was made
    period: str  # "morning", "afternoon"... when it was made
    complete: bool  # False if the weather couldn't be fetched


def current_period() -> str:
    return time_of_day(datetime.now())


class BriefingCache:
    """Holds one ready-to-play briefing and remakes it in the background.

    A briefing is remade when it's used, when it's older than ``max_age``
    seconds, or when the time of day changes (so "good morning" doesn't play
    in the afternoon). One made without weather is retried sooner.
    """

    def __init__(
        self,
        build: Callable[[], Briefing],
        max_age: float,
        incomplete_max_age: float = 120.0,
        retry_delay: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        period: Callable[[], str] = current_period,
    ):
        self.build = build
        self.max_age = max_age
        self.incomplete_max_age = incomplete_max_age
        self.retry_delay = retry_delay
        self.clock = clock
        self.period = period
        self._cond = threading.Condition()
        self._ready: Briefing | None = None
        self._stopped = False
        self._thread: threading.Thread | None = None

    def is_fresh(self, briefing: Briefing) -> bool:
        age = self.clock() - briefing.made_at
        limit = self.max_age if briefing.complete else self.incomplete_max_age
        return age < limit and briefing.period == self.period()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._worker, name="briefing", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify_all()

    def take(self, timeout: float = 0.0) -> Briefing | None:
        """Hand over the ready briefing, waiting up to ``timeout`` seconds for one.

        Returns None if nothing fresh is ready in time. Taking a briefing
        starts the next one being made.
        """
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                briefing, self._ready = self._ready, None
                if briefing is not None:
                    self._cond.notify_all()  # wake the worker to make the next one
                    if self.is_fresh(briefing):
                        return briefing
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._stopped:
                    return None
                self._cond.wait(timeout=remaining)

    def _worker(self) -> None:
        while True:
            with self._cond:
                # Sleep while there's a fresh briefing waiting; check again
                # every 30 seconds in case it has gone stale.
                while not self._stopped and self._ready and self.is_fresh(self._ready):
                    self._cond.wait(timeout=30)
                if self._stopped:
                    return
            try:
                briefing = self.build()
            except Exception as exc:
                print(f"(Couldn't prepare the next greeting: {exc})")
                briefing = None
            with self._cond:
                if briefing is not None:
                    self._ready = briefing
                    self._cond.notify_all()
                elif not self._stopped:
                    self._cond.wait(timeout=self.retry_delay)
