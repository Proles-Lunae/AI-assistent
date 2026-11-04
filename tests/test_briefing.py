import itertools

from assistant.briefing import Briefing, BriefingCache
from assistant.voice import Speech


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make_cache(clock, period=lambda: "morning", complete=True, max_age=1200):
    counter = itertools.count(1)
    built = []

    def build():
        n = next(counter)
        built.append(n)
        return Briefing(Speech(f"briefing {n}"), clock(), period(), complete)

    cache = BriefingCache(build, max_age=max_age, clock=clock, period=period, retry_delay=0.01)
    return cache, built


def test_take_returns_prepared_briefing_and_makes_the_next():
    clock = FakeClock()
    cache, built = make_cache(clock)
    cache.start()
    try:
        first = cache.take(timeout=2)
        second = cache.take(timeout=2)
        assert first.speech.text == "briefing 1"
        assert second.speech.text == "briefing 2"
    finally:
        cache.stop()


def test_stale_briefing_is_not_played():
    clock = FakeClock()
    cache = BriefingCache(lambda: None, max_age=60, clock=clock, period=lambda: "morning")
    cache._ready = Briefing(Speech("old"), made_at=0, period="morning", complete=True)
    clock.now = 61
    assert cache.take(timeout=0) is None


def test_briefing_from_another_time_of_day_is_not_played():
    clock = FakeClock()
    period = ["morning"]
    cache = BriefingCache(lambda: None, max_age=1200, clock=clock, period=lambda: period[0])
    cache._ready = Briefing(Speech("good morning"), made_at=0, period="morning", complete=True)
    period[0] = "afternoon"
    assert cache.take(timeout=0) is None


def test_briefing_without_weather_expires_sooner():
    clock = FakeClock()
    cache = BriefingCache(lambda: None, max_age=1200, incomplete_max_age=120, clock=clock)
    b = Briefing(Speech("no weather"), made_at=0, period=cache.period(), complete=False)
    clock.now = 100
    assert cache.is_fresh(b)
    clock.now = 130
    assert not cache.is_fresh(b)


def test_failed_build_is_retried():
    clock = FakeClock()
    attempts = []

    def build():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("network down")
        return Briefing(Speech("finally"), clock(), "morning", True)

    cache = BriefingCache(build, max_age=1200, clock=clock, period=lambda: "morning", retry_delay=0.01)
    cache.start()
    try:
        assert cache.take(timeout=2).speech.text == "finally"
        assert len(attempts) == 3
    finally:
        cache.stop()


def test_stop_ends_worker():
    clock = FakeClock()
    cache, _ = make_cache(clock)
    cache.start()
    cache.take(timeout=2)
    cache.stop()
    cache._thread.join(timeout=2)
    assert not cache._thread.is_alive()
