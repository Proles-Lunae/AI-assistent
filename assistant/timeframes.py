"""The day's three time frames, and the greeting for each.

A time frame is identified by the moment it starts: at 1am on 3 January the
current frame is the evening that started at 6pm on 2 January. That tells one
evening apart from the next, even if the computer slept in between.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# (name, hour it starts, greeting), in the order of the day. Each frame lasts
# until the next one starts, so the last one runs past midnight.
TIME_FRAMES = (
    ("morning", 3, "Good morning"),  # 3am - 11am
    ("afternoon", 11, "Good afternoon"),  # 11am - 6pm
    ("evening", 18, "Good evening"),  # 6pm - 3am
)
GREETINGS = {name: greeting for name, _, greeting in TIME_FRAMES}


def _frame_index(when: datetime) -> int:
    # Before the first frame starts (after midnight), it's still the last one.
    return max((i for i, (_, hour, _) in enumerate(TIME_FRAMES) if when.hour >= hour), default=-1)


def time_of_day(when: datetime) -> str:
    """'morning' (3am-11am), 'afternoon' (11am-6pm) or 'evening' (6pm-3am)."""
    return TIME_FRAMES[_frame_index(when)][0]


def frame_start(when: datetime) -> datetime:
    """When the time frame containing ``when`` began, e.g. 6pm yesterday at 1am."""
    start = when.replace(hour=TIME_FRAMES[_frame_index(when)][1], minute=0, second=0, microsecond=0)
    return start - timedelta(days=1) if start > when else start


def frame_end(when: datetime) -> datetime:
    """When the time frame containing ``when`` ends, i.e. when the next one starts."""
    start = frame_start(when)
    next_hour = TIME_FRAMES[(_frame_index(start) + 1) % len(TIME_FRAMES)][1]
    end = start.replace(hour=next_hour)
    return end if end > start else end + timedelta(days=1)


def standard_greeting(period: str, name: str = "") -> str:
    """The greeting for a time frame, e.g. 'Good morning, sir.'"""
    return GREETINGS[period] + (f", {name}" if name else "") + "."
