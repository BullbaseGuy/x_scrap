from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from x_scrap.domain.models import (
    CoverageStatus,
    WindowStatus,
    iso_utc,
    parse_datetime,
)
from x_scrap.security import is_within

KNOWN_SOURCE_LIMITATIONS = [
    "deleted, suspended, protected, de-indexed, or search-suppressed posts may be unavailable",
    "historical native repost indexing is not guaranteed",
    "X internal GraphQL and search behavior may change without notice",
]


def _window_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "window_id": row.get("window_id"),
        "source": row.get("source"),
        "start_at": row.get("start_at"),
        "end_at": row.get("end_at"),
        "depth": row.get("depth"),
        "status": row.get("status"),
        "post_count": row.get("post_count"),
        "terminal_reason": row.get("terminal_reason"),
    }


def _error(code: str, **context: Any) -> dict[str, Any]:
    return {"code": code, **context}


def audit_coverage(
    windows: list[dict[str, Any]], start: datetime, end: datetime
) -> dict[str, Any]:
    """Validate that terminal leaf windows form one exact half-open partition."""

    leaves = [row for row in windows if row.get("status") != WindowStatus.SPLIT.value]
    unresolved = [
        _window_summary(row)
        for row in leaves
        if row.get("status") != WindowStatus.COMPLETE.value
    ]
    parsed: list[tuple[datetime, datetime, dict[str, Any]]] = []
    partition_errors: list[dict[str, Any]] = []
    for row in leaves:
        row_start = parse_datetime(row.get("start_at"))
        row_end = parse_datetime(row.get("end_at"))
        reference = {"window_id": row.get("window_id")}
        if row_start is None or row_end is None:
            partition_errors.append(_error("INVALID_WINDOW_TIMESTAMP", **reference))
            continue
        if row_start >= row_end:
            partition_errors.append(_error("INVALID_WINDOW_RANGE", **reference))
            continue
        if row_start < start or row_end > end:
            partition_errors.append(
                _error(
                    "WINDOW_OUTSIDE_FROZEN_RANGE",
                    **reference,
                    start_at=iso_utc(row_start),
                    end_at=iso_utc(row_end),
                )
            )
        parsed.append((row_start, row_end, row))

    gaps: list[dict[str, str]] = []
    overlaps: list[dict[str, str]] = []
    cursor = start
    for row_start, row_end, _ in sorted(parsed, key=lambda item: (item[0], item[1])):
        if row_start > cursor:
            gaps.append({"start": iso_utc(cursor), "end": iso_utc(row_start)})
        elif row_start < cursor:
            overlaps.append({"start": iso_utc(row_start), "end": iso_utc(min(cursor, row_end))})
        cursor = max(cursor, row_end)
    if cursor < end:
        gaps.append({"start": iso_utc(cursor), "end": iso_utc(end)})
    elif cursor > end:
        overlaps.append({"start": iso_utc(end), "end": iso_utc(cursor)})

    complete = [row for row in leaves if row.get("status") == WindowStatus.COMPLETE.value]
    status = (
        CoverageStatus.COMPLETE_PUBLICLY_RETRIEVABLE
        if leaves
        and not unresolved
        and not gaps
        and not overlaps
        and not partition_errors
        else CoverageStatus.PARTIAL_UNRESOLVED_WINDOWS
    )
    return {
        "schema_version": "2.0.0",
        "status": status.value,
        "range": {"start_at": iso_utc(start), "cutoff_at": iso_utc(end)},
        "window_count": len(windows),
        "leaf_window_count": len(leaves),
        "complete_window_count": len(complete),
        "unresolved_windows": unresolved,
        "gaps": gaps,
        "overlaps": overlaps,
        "partition_errors": partition_errors,
        "known_source_limitations": list(KNOWN_SOURCE_LIMITATIONS),
    }


def audit_collection(
    windows: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    *,
    scopes: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    page_links: list[dict[str, Any]],
    posts: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    raw_root: Path,
) -> dict[str, Any]:
    """Cross-check the complete persisted evidence graph before export."""

    result = audit_coverage(windows, start, end)
    errors: list[dict[str, Any]] = []
    scope_by_key = {str(row["scope_key"]): row for row in scopes}
    pages_by_scope: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for page in pages:
        pages_by_scope[str(page["scope_key"])].append(page)
    links_by_page: dict[tuple[str, int], list[str]] = defaultdict(list)
    link_sources_by_post: dict[str, set[str]] = defaultdict(set)
    for link in page_links:
        scope_key = str(link["scope_key"])
        page_index = int(link["page_index"])
        post_id = str(link["post_id"])
        links_by_page[(scope_key, page_index)].append(post_id)
        link_sources_by_post[post_id].add(str(link["source"]))

    posts_by_id: dict[str, dict[str, Any]] = {}
    for post in posts:
        post_id = post.get("post_id")
        if not isinstance(post_id, str) or not post_id:
            errors.append(_error("POST_ID_NOT_STRING"))
            continue
        if post_id in posts_by_id:
            errors.append(_error("DUPLICATE_EXPORTED_POST_ID", post_id=post_id))
            continue
        posts_by_id[post_id] = post
        created_at = parse_datetime(post.get("created_at"))
        if created_at is None:
            errors.append(_error("POST_TIMESTAMP_INVALID", post_id=post_id))
        elif not (start <= created_at < end):
            errors.append(
                _error(
                    "POST_OUTSIDE_FROZEN_RANGE",
                    post_id=post_id,
                    created_at=iso_utc(created_at),
                )
            )
        stored_sources = sorted({str(source) for source in post.get("sources", [])})
        linked_sources = sorted(link_sources_by_post.get(post_id, set()))
        if stored_sources != linked_sources:
            errors.append(
                _error(
                    "POST_SOURCE_PROVENANCE_MISMATCH",
                    post_id=post_id,
                    stored_sources=stored_sources,
                    linked_sources=linked_sources,
                )
            )

    for post_id in sorted(link_sources_by_post):
        if post_id not in posts_by_id:
            errors.append(_error("PAGE_LINK_REFERENCES_MISSING_POST", post_id=post_id))
    for post_id in sorted(posts_by_id):
        if post_id not in link_sources_by_post:
            errors.append(_error("POST_HAS_NO_PAGE_PROVENANCE", post_id=post_id))

    raw_root = raw_root.expanduser().resolve(strict=False)
    raw_checked = 0
    raw_failed = 0
    for scope_key, scope in sorted(scope_by_key.items()):
        scope_pages = sorted(
            pages_by_scope.get(scope_key, []), key=lambda row: int(row["page_index"])
        )
        expected_cursor: str | None = None
        for expected_index, page in enumerate(scope_pages):
            page_index = int(page["page_index"])
            reference = {"scope_key": scope_key, "page_index": page_index}
            if page_index != expected_index:
                errors.append(
                    _error(
                        "NON_CONTIGUOUS_PAGE_INDEX",
                        **reference,
                        expected_page_index=expected_index,
                    )
                )
            if page.get("request_cursor") != expected_cursor:
                errors.append(_error("PAGE_CURSOR_CHAIN_MISMATCH", **reference))
            expected_cursor = page.get("next_cursor")
            if page.get("source") != scope.get("source"):
                errors.append(_error("PAGE_SCOPE_SOURCE_MISMATCH", **reference))

            linked_ids = sorted(set(links_by_page.get((scope_key, page_index), [])))
            if int(page.get("accepted_count", 0)) != len(linked_ids):
                errors.append(
                    _error(
                        "PAGE_ACCEPTED_COUNT_MISMATCH",
                        **reference,
                        stored_count=int(page.get("accepted_count", 0)),
                        linked_count=len(linked_ids),
                    )
                )
            if int(page.get("item_count", 0)) < int(page.get("accepted_count", 0)):
                errors.append(_error("PAGE_ACCEPTED_EXCEEDS_ITEMS", **reference))

            linked_times = [
                parse_datetime(posts_by_id[post_id].get("created_at"))
                for post_id in linked_ids
                if post_id in posts_by_id
            ]
            valid_times = [value for value in linked_times if value is not None]
            expected_oldest = iso_utc(min(valid_times)) if valid_times else None
            expected_newest = iso_utc(max(valid_times)) if valid_times else None
            if page.get("oldest_post_at") != expected_oldest:
                errors.append(_error("PAGE_OLDEST_TIMESTAMP_MISMATCH", **reference))
            if page.get("newest_post_at") != expected_newest:
                errors.append(_error("PAGE_NEWEST_TIMESTAMP_MISMATCH", **reference))

            artifact = Path(str(page.get("artifact_path", ""))).resolve(strict=False)
            raw_checked += 1
            artifact_error = _verify_raw_artifact(page, artifact, raw_root)
            if artifact_error is not None:
                raw_failed += 1
                errors.append(_error(artifact_error, **reference))

        if int(scope.get("next_page_index", 0)) != len(scope_pages):
            errors.append(
                _error(
                    "SCOPE_NEXT_PAGE_INDEX_MISMATCH",
                    scope_key=scope_key,
                    next_page_index=scope.get("next_page_index"),
                    page_count=len(scope_pages),
                )
            )
        if scope.get("next_cursor") != expected_cursor:
            errors.append(_error("SCOPE_NEXT_CURSOR_MISMATCH", scope_key=scope_key))
        state = str(scope.get("state"))
        if state == "COMPLETE" and scope.get("next_cursor") is not None:
            errors.append(_error("COMPLETE_SCOPE_HAS_CURSOR", scope_key=scope_key))
        if state == "LIMIT_REACHED" and scope.get("next_cursor") is None:
            errors.append(_error("LIMITED_SCOPE_HAS_NO_CURSOR", scope_key=scope_key))
        if state not in {"COMPLETE", "LIMIT_REACHED"}:
            errors.append(
                _error("NON_TERMINAL_SCOPE", scope_key=scope_key, state=state)
            )

    for scope_key in sorted(set(pages_by_scope) - set(scope_by_key)):
        errors.append(_error("PAGE_HAS_NO_SCOPE", scope_key=scope_key))

    window_scope_keys: set[str] = set()
    for window in windows:
        window_id = str(window.get("window_id"))
        scope_key = f"window:{window_id}"
        window_scope_keys.add(scope_key)
        scope = scope_by_key.get(scope_key)
        if scope is None:
            errors.append(_error("WINDOW_HAS_NO_SEARCH_SCOPE", window_id=window_id))
            continue
        if scope.get("source") != "search":
            errors.append(_error("WINDOW_SCOPE_SOURCE_MISMATCH", window_id=window_id))

        scope_pages = pages_by_scope.get(scope_key, [])
        linked_ids = {
            post_id
            for page in scope_pages
            for post_id in links_by_page.get((scope_key, int(page["page_index"])), [])
        }
        linked_times = [
            parse_datetime(posts_by_id[post_id].get("created_at"))
            for post_id in linked_ids
            if post_id in posts_by_id
        ]
        valid_times = [value for value in linked_times if value is not None]
        expected_oldest = iso_utc(min(valid_times)) if valid_times else None
        expected_newest = iso_utc(max(valid_times)) if valid_times else None
        if int(window.get("post_count", 0)) != len(linked_ids):
            errors.append(_error("WINDOW_POST_COUNT_MISMATCH", window_id=window_id))
        if window.get("oldest_post_at") != expected_oldest:
            errors.append(_error("WINDOW_OLDEST_TIMESTAMP_MISMATCH", window_id=window_id))
        if window.get("newest_post_at") != expected_newest:
            errors.append(_error("WINDOW_NEWEST_TIMESTAMP_MISMATCH", window_id=window_id))

        expected_state = {
            WindowStatus.COMPLETE.value: "COMPLETE",
            WindowStatus.SPLIT.value: "LIMIT_REACHED",
            WindowStatus.PARTIAL_LIMIT_REACHED.value: "LIMIT_REACHED",
            WindowStatus.FAILED.value: "FAILED",
        }.get(str(window.get("status")))
        if expected_state is not None and scope.get("state") != expected_state:
            errors.append(
                _error(
                    "WINDOW_SCOPE_STATE_MISMATCH",
                    window_id=window_id,
                    window_status=window.get("status"),
                    scope_state=scope.get("state"),
                )
            )

    extra_search_scopes = {
        key
        for key, scope in scope_by_key.items()
        if scope.get("source") == "search" and key not in window_scope_keys
    }
    for scope_key in sorted(extra_search_scopes):
        errors.append(_error("SEARCH_SCOPE_HAS_NO_WINDOW", scope_key=scope_key))

    state_counts = Counter(str(scope.get("state")) for scope in scopes)
    source_counts = Counter(
        str(source)
        for post in posts
        for source in sorted({str(value) for value in post.get("sources", [])})
    )
    conflict_post_ids = sorted({str(row.get("post_id")) for row in conflicts})
    integrity_status = "PASS" if not errors else "FAIL"
    if conflicts:
        status = CoverageStatus.SOURCE_CONFLICT.value
    elif result["status"] != CoverageStatus.COMPLETE_PUBLICLY_RETRIEVABLE.value or errors:
        status = CoverageStatus.PARTIAL_UNRESOLVED_WINDOWS.value
    else:
        status = CoverageStatus.COMPLETE_PUBLICLY_RETRIEVABLE.value

    result.update(
        {
            "status": status,
            "integrity": {
                "status": integrity_status,
                "error_count": len(errors),
                "errors": errors,
                "post_count": len(posts_by_id),
                "scope_count": len(scopes),
                "page_count": len(pages),
                "page_link_count": len(page_links),
                "raw_artifacts_checked": raw_checked,
                "raw_artifacts_failed": raw_failed,
            },
            "conflicts": {
                "count": len(conflicts),
                "post_ids": conflict_post_ids,
            },
            "scope_state_counts": dict(sorted(state_counts.items())),
            "source_counts": dict(sorted(source_counts.items())),
        }
    )
    return result


def _verify_raw_artifact(
    page: dict[str, Any], artifact: Path, raw_root: Path
) -> str | None:
    if not is_within(artifact, raw_root):
        return "RAW_ARTIFACT_OUTSIDE_ROOT"
    if not artifact.is_file():
        return "RAW_ARTIFACT_MISSING"
    try:
        compressed = artifact.read_bytes()
    except OSError:
        return "RAW_ARTIFACT_UNREADABLE"
    if len(compressed) != int(page.get("artifact_size", -1)):
        return "RAW_ARTIFACT_SIZE_MISMATCH"
    if hashlib.sha256(compressed).hexdigest() != page.get("payload_sha256"):
        return "RAW_ARTIFACT_HASH_MISMATCH"
    try:
        json.loads(gzip.decompress(compressed))
    except (OSError, EOFError, gzip.BadGzipFile, json.JSONDecodeError, UnicodeDecodeError):
        return "RAW_ARTIFACT_INVALID_JSON_GZIP"
    return None
