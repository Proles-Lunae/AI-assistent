import itertools
from datetime import datetime

from assistant.briefing import Briefing, BriefingCache
from assistant.voice import Speech

MORNING = datetime(2026, 1, 2, 3)
AFTERNOON = datetime(2026, 1, 2, 11)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make_cache(clock, frame):
    counter = itertools.count(1)
    built = []

    def build():
        n = next(counter)
        built.append(n)
        return Briefing(Speech(f"briefing {n}"), frame[0], clock(), True)

    cache = BriefingCache(build, clock=clock, frame=lambda: frame[0], retry_delay=0.01)
    return cache, built


def test_same_briefing_is_reused_within_a_time_frame():
    clock, frame = FakeClock(), [MORNING]
    cache, built = make_cache(clock, frame)
    cache.start()
    try:
        first = cache.take(timeout=2)
        clock.now = 3 * 3600  # hours later, still the same frame
        second = cache.take(timeout=2)
        assert first is second
        assert built == [1]
    finally:
        cache.stop()


def test_new_briefing_when_time_frame_changes():
    clock, frame = FakeClock(), [MORNING]
    cache, built = make_cache(clock, frame)
    cache.start()
    try:
        assert cache.take(timeout=2).speech.text == "briefing 1"
        frame[0] = AFTERNOON
        assert cache.take(timeout=2).speech.text == "briefing 2"
    finally:
        cache.stop()


def test_briefing_from_an_earlier_frame_is_not_played():
    cache = BriefingCache(lambda: None, frame=lambda: AFTERNOON)
    cache._ready = Briefing(Speech("old"), MORNING, made_at=0, complete=True)
    assert cache.take(timeout=0) is None


def test_briefing_without_weather_expires_sooner():
    clock = FakeClock()
    cache = BriefingCache(lambda: None, incomplete_max_age=120, clock=clock, frame=lambda: MORNING)
    b = Briefing(Speech("no weather"), MORNING, made_at=0, complete=False)
    clock.now = 100
    assert cache.is_fresh(b)
    clock.now = 130
    assert not cache.is_fresh(b)


def test_failed_build_is_retried():
    attempts = []

    def build():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("network down")
        return Briefing(Speech("finally"), MORNING, 0, True)

    cache = BriefingCache(build, frame=lambda: MORNING, retry_delay=0.01)
    cache.start()
    try:
        assert cache.take(timeout=2).speech.text == "finally"
        assert len(attempts) == 3
    finally:
        cache.stop()


def test_stop_ends_worker():
    clock, frame = FakeClock(), [MORNING]
    cache, _ = make_cache(clock, frame)
    cache.start()
    cache.take(timeout=2)
    cache.stop()
    cache._thread.join(timeout=2)
    assert not cache._thread.is_alive()
