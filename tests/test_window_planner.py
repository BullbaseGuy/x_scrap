from datetime import datetime, timedelta, timezone

from x_scrap.harvest.window_planner import build_search_query, make_windows, split_window

UTC = timezone.utc


def test_windows_cover_range_without_gaps():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 3, 10, tzinfo=UTC)
    windows = make_windows(start, end, days=30)
    assert windows[0].start == start
    assert windows[-1].end == end
    assert all(a.end == b.start for a, b in zip(windows, windows[1:]))


def test_split_preserves_exact_coverage():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    window = make_windows(start, start + timedelta(days=2), days=30)[0]
    left, right = split_window(window)
    assert left.start == window.start
    assert left.end == right.start
    assert right.end == window.end
    assert left.depth == right.depth == 1


def test_search_query_uses_epoch_boundaries_and_excludes_native_retweets():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    window = make_windows(start, start + timedelta(days=1), days=1)[0]
    query = build_search_query("@alice", window, include_retweets=False)
    assert "from:alice" in query
    assert "since_time:" in query and "until_time:" in query
    assert "-filter:nativeretweets" in query
