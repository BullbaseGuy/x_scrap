from datetime import UTC, datetime, timedelta

import pytest

from x_scrap.domain.models import TimeWindow
from x_scrap.harvest.window_planner import build_search_query, make_windows, split_window


def test_windows_cover_range_without_gaps():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 3, 10, tzinfo=UTC)
    windows = make_windows(start, end, days=30)
    assert windows[0].start == start
    assert windows[-1].end == end
    assert all(a.end == b.start for a, b in zip(windows, windows[1:], strict=False))


def test_split_preserves_exact_integer_second_coverage_for_odd_duration():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    window = TimeWindow(start, start + timedelta(seconds=5))
    left, right = split_window(window)
    assert left.start == window.start
    assert left.duration_seconds == 2
    assert left.end == right.start
    assert right.duration_seconds == 3
    assert right.end == window.end
    assert left.depth == right.depth == 1


def test_one_second_window_cannot_be_split():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="cannot be split"):
        split_window(TimeWindow(start, start + timedelta(seconds=1)))


def test_window_rejects_fractional_second_boundaries():
    start = datetime(2026, 1, 1, microsecond=1, tzinfo=UTC)
    with pytest.raises(ValueError, match="whole-second"):
        TimeWindow(start, start + timedelta(seconds=2))


def test_search_query_uses_canonical_username_and_epoch_boundaries():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    window = make_windows(start, start + timedelta(days=1), days=1)[0]
    query = build_search_query("@Alice_Canonical", window, include_retweets=False)
    assert "from:Alice_Canonical" in query
    assert f"since_time:{int(start.timestamp())}" in query
    assert f"until_time:{int((start + timedelta(days=1)).timestamp())}" in query
    assert "-filter:nativeretweets" in query


def test_search_query_rejects_operator_injection_in_resolved_username():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    window = TimeWindow(start, start + timedelta(seconds=2))
    with pytest.raises(ValueError, match="unsupported"):
        build_search_query("alice OR from:bob", window, include_retweets=False)


def test_split_is_contiguous_for_many_integer_second_durations():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for seconds in range(2, 101):
        parent = TimeWindow(start, start + timedelta(seconds=seconds))
        left, right = split_window(parent)
        assert left.start == parent.start
        assert left.end == right.start
        assert right.end == parent.end
        assert left.duration_seconds + right.duration_seconds == seconds
        assert abs(left.duration_seconds - right.duration_seconds) <= 1
