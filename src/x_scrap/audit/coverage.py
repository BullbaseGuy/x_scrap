from __future__ import annotations

from datetime import datetime
from typing import Any

from x_scrap.domain.models import CoverageStatus, WindowStatus, parse_datetime


def audit_coverage(windows: list[dict[str, Any]], start: datetime, end: datetime) -> dict[str, Any]:
    leaves = [row for row in windows if row["status"] != WindowStatus.SPLIT.value]
    unresolved = [
        row
        for row in leaves
        if row["status"] not in {WindowStatus.COMPLETE.value}
    ]
    complete = sorted(
        (row for row in leaves if row["status"] == WindowStatus.COMPLETE.value),
        key=lambda row: row["start_at"],
    )
    gaps: list[dict[str, str]] = []
    cursor = start
    for row in complete:
        row_start = parse_datetime(row["start_at"])
        row_end = parse_datetime(row["end_at"])
        if row_start is None or row_end is None:
            continue
        if row_start > cursor:
            gaps.append({"start": cursor.isoformat(), "end": row_start.isoformat()})
        cursor = max(cursor, row_end)
    if cursor < end:
        gaps.append({"start": cursor.isoformat(), "end": end.isoformat()})
    status = (
        CoverageStatus.COMPLETE_PUBLICLY_RETRIEVABLE
        if not unresolved and not gaps
        else CoverageStatus.PARTIAL_UNRESOLVED_WINDOWS
    )
    return {
        "status": status.value,
        "window_count": len(leaves),
        "complete_window_count": len(complete),
        "unresolved_windows": unresolved,
        "gaps": gaps,
        "known_source_limitations": [
            "deleted, suspended, protected, de-indexed, or search-suppressed posts may be unavailable",
            "historical native repost indexing is not guaranteed",
            "X internal GraphQL and search behavior may change without notice",
        ],
    }
