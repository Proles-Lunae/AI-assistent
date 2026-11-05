from datetime import datetime

from assistant.briefing import Briefing, BriefingCache
from assistant.voice import Speech

MORNING = datetime(2026, 1, 2, 3)
AFTERNOON = datetime(2026, 1, 2, 11)
EVENING = datetime(2026, 1, 2, 18)


class Fake:
    """A settable value that can be called, for the clock and the date/time."""

    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


def make_cache(now, clock=None, complete=True, fail_times=0):
    clock = clock or Fake(0.0)
    built = []

    def build(frame):
        if len([b for b in built if b == "fail"]) < fail_times:
            built.append("fail")
            raise RuntimeError("network down")
        built.append(frame)
        return Briefing(Speech(f"briefing for {frame:%H}"), "forecast", frame, clock(), complete)

    cache = BriefingCache(build, clock=clock, now=now, retry_delay=0.01)
    return cache, built


def test_greeting_and_forecast_are_ready_for_the_current_frame():
    now = Fake(datetime(2026, 1, 2, 8))
    cache, built = make_cache(now)
    cache.start()
    try:
        assert cache.take(timeout=2).speech.text == "briefing for 03"
        assert built == [MORNING]
    finally:
        cache.stop()


def test_same_briefing_is_reused_within_a_frame():
    now = Fake(datetime(2026, 1, 2, 4))
    cache, built = make_cache(now)
    cache.start()
    try:
        first = cache.take(timeout=2)
        now.value = datetime(2026, 1, 2, 9)  # hours later, still morning
        assert cache.take(timeout=2) is first
        assert built == [MORNING]
    finally:
        cache.stop()


def test_next_frame_is_prepared_30_minutes_early():
    now = Fake(datetime(2026, 1, 2, 10, 0))
    cache, _ = make_cache(now)
    assert cache.wanted_frames() == [MORNING]
    now.value = datetime(2026, 1, 2, 10, 31)
    assert cache.wanted_frames() == [MORNING, AFTERNOON]
    now.value = datetime(2026, 1, 3, 2, 40)  # evening into the night -> next morning
    assert cache.wanted_frames() == [datetime(2026, 1, 2, 18), datetime(2026, 1, 3, 3)]


def test_frame_change_plays_the_ready_next_briefing_without_waiting():
    now = Fake(datetime(2026, 1, 2, 17, 45))
    cache, built = make_cache(now)
    cache.start()
    try:
        cache.take(timeout=2)
        for _ in range(200):  # wait until the evening one has been made too
            if EVENING in built:
                break
            cache._thread.join(timeout=0.01)
        now.value = datetime(2026, 1, 2, 18, 0, 5)
        assert cache.take(timeout=0).speech.text == "briefing for 18"
        assert built == [AFTERNOON, EVENING]
    finally:
        cache.stop()


def test_finished_frames_are_forgotten():
    now = Fake(datetime(2026, 1, 2, 12))
    cache, _ = make_cache(now)
    cache._ready[MORNING] = Briefing(Speech("old"), "", MORNING, 0, True)
    assert cache.next_to_build() == AFTERNOON
    assert MORNING not in cache._ready
    assert cache.take(timeout=0) is None


def test_briefing_without_weather_is_remade_soon():
    clock = Fake(0.0)
    now = Fake(datetime(2026, 1, 2, 8))
    cache, _ = make_cache(now, clock=clock)
    b = Briefing(Speech("no weather"), "", MORNING, made_at=0, complete=False)
    cache._ready[MORNING] = b
    clock.value = 100
    assert cache.usable(b) and cache.next_to_build() is None
    clock.value = 130
    assert not cache.usable(b) and cache.next_to_build() == MORNING


def test_failed_build_is_retried():
    now = Fake(datetime(2026, 1, 2, 8))
    cache, built = make_cache(now, fail_times=2)
    cache.start()
    try:
        assert cache.take(timeout=2).speech.text == "briefing for 03"
        assert built == ["fail", "fail", MORNING]
    finally:
        cache.stop()


def test_stop_ends_worker():
    cache, _ = make_cache(Fake(datetime(2026, 1, 2, 8)))
    cache.start()
    cache.take(timeout=2)
    cache.stop()
    cache._thread.join(timeout=2)
    assert not cache._thread.is_alive()


def test_old_briefing_keeps_playing_while_it_is_remade():
    clock = Fake(0.0)
    now = Fake(datetime(2026, 1, 2, 8))
    cache, _ = make_cache(now, clock=clock)
    stand_in = Briefing(Speech("no weather"), "", MORNING, made_at=0, complete=False)
    cache._ready[MORNING] = stand_in
    clock.value = 500  # long past the 2 minutes: due for remaking...
    assert cache.next_to_build() == MORNING
    assert cache.take(timeout=0) is stand_in  # ...but a clap still gets it at once


def test_quick_version_is_kept_but_never_replaces_claudes():
    cache, _ = make_cache(Fake(datetime(2026, 1, 2, 8)))
    claudes = Briefing(Speech("Claude"), "", MORNING, 0, True)
    quick = Briefing(Speech("quick"), "", MORNING, 0, False)
    cache.offer(quick)
    assert cache.take(timeout=0) is quick
    cache._ready[MORNING] = claudes  # what the worker does when Claude is done
    cache.offer(Briefing(Speech("quick again"), "", MORNING, 0, False))
    assert cache.take(timeout=0) is claudes
