from __future__ import annotations

import re
from datetime import datetime, timedelta

from x_scrap.domain.models import TimeWindow, ensure_utc

_USERNAME_RE = re.compile(r"[A-Za-z0-9_]+")


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
    start_epoch = int(window.start.timestamp())
    end_epoch = int(window.end.timestamp())
    duration = end_epoch - start_epoch
    if duration < 2:
        raise ValueError("a one-second window cannot be split")
    midpoint_epoch = start_epoch + duration // 2
    midpoint = datetime.fromtimestamp(midpoint_epoch, tz=window.start.tzinfo)
    left = TimeWindow(window.start, midpoint, window.depth + 1)
    right = TimeWindow(midpoint, window.end, window.depth + 1)
    return left, right


def build_search_query(username: str, window: TimeWindow, *, include_retweets: bool) -> str:
    canonical = username.strip().lstrip("@")
    if not canonical or _USERNAME_RE.fullmatch(canonical) is None:
        raise ValueError("resolved username contains unsupported search characters")
    parts = [
        f"from:{canonical}",
        f"since_time:{int(window.start.timestamp())}",
        f"until_time:{int(window.end.timestamp())}",
    ]
    if not include_retweets:
        parts.append("-filter:nativeretweets")
    return " ".join(parts)
