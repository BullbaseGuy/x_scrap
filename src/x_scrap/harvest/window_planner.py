from __future__ import annotations

from datetime import datetime, timedelta

from x_scrap.domain.models import TimeWindow, ensure_utc


def make_windows(start: datetime, end: datetime, *, days: int = 30) -> list[TimeWindow]:
    if days < 1:
        raise ValueError("days must be positive")
    start = ensure_utc(start)
    end = ensure_utc(end)
    if start >= end:
        return []
    step = timedelta(days=days)
    windows: list[TimeWindow] = []
    cursor = start
    while cursor < end:
        next_cursor = min(cursor + step, end)
        windows.append(TimeWindow(cursor, next_cursor))
        cursor = next_cursor
    return windows


def split_window(window: TimeWindow) -> tuple[TimeWindow, TimeWindow]:
    midpoint = window.start + (window.end - window.start) / 2
    left = TimeWindow(window.start, midpoint, window.depth + 1)
    right = TimeWindow(midpoint, window.end, window.depth + 1)
    return left, right


def build_search_query(username: str, window: TimeWindow, *, include_retweets: bool) -> str:
    parts = [
        f"from:{username.lstrip('@')}",
        f"since_time:{int(window.start.timestamp())}",
        f"until_time:{int(window.end.timestamp())}",
    ]
    if not include_retweets:
        parts.append("-filter:nativeretweets")
    return " ".join(parts)
