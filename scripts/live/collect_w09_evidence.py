from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from x_scrap.config import AppPaths
from x_scrap.export.writer import verify_export_bundle
from x_scrap.security import (
    redact_text,
    redact_value,
    reject_git_worktree_state_home,
    write_private_text,
)
from x_scrap.storage.database import Database
from x_scrap.storage.page_repository import PageRepository

_EVIDENCE_SCHEMA = "1.0.0"
_RECOVERY_EVENTS = {"RATE_LIMIT_WAIT", "TRANSIENT_RETRY", "RECOVERY_EXHAUSTED"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a redacted W09 evidence summary from local x_scrap state. "
            "This command never reads or emits browser Cookie values."
        )
    )
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        help="private JSON output path; defaults under X_SCRAP_HOME/w09-evidence",
    )
    return parser


def _cursor_fingerprint(value: object | None) -> str | None:
    if value is None or value == "":
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _page_position(page: dict[str, Any] | None) -> dict[str, Any] | None:
    if page is None:
        return None
    return {
        "scope_key": page.get("scope_key"),
        "page_index": page.get("page_index"),
        "request_cursor_fingerprint": _cursor_fingerprint(page.get("request_cursor")),
        "next_cursor_fingerprint": _cursor_fingerprint(page.get("next_cursor")),
        "payload_sha256": page.get("payload_sha256"),
        "committed_at": page.get("committed_at"),
    }


def _run_segments(
    events: list[dict[str, Any]], pages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    page_lookup = {
        (str(page.get("scope_key")), int(page.get("page_index", 0))): page
        for page in pages
    }
    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for event in events:
        event_type = str(event.get("event_type", ""))
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        if event_type == "JOB_STARTED":
            if current is not None:
                segments.append(current)
            current = {
                "started_event_id": event.get("event_id"),
                "started_at": event.get("occurred_at"),
                "resume": bool(details.get("resume")),
                "pages": [],
            }
            continue
        if event_type != "PAGE_COMMITTED" or current is None:
            continue
        key = (str(details.get("scope_key")), int(details.get("page_index", 0)))
        page = page_lookup.get(key)
        current["pages"].append(_page_position(page) or {
            "scope_key": key[0],
            "page_index": key[1],
            "request_cursor_fingerprint": None,
            "next_cursor_fingerprint": None,
            "payload_sha256": details.get("payload_sha256"),
            "committed_at": event.get("occurred_at"),
        })
    if current is not None:
        segments.append(current)

    summarized: list[dict[str, Any]] = []
    for index, segment in enumerate(segments, start=1):
        committed = segment.pop("pages")
        summarized.append(
            {
                **segment,
                "run_index": index,
                "committed_page_count": len(committed),
                "first_committed_page": committed[0] if committed else None,
                "last_committed_page": committed[-1] if committed else None,
            }
        )
    return summarized


def build_evidence(home: Path, job_id: str) -> dict[str, Any]:
    paths = AppPaths.discover(home).ensure()
    database = Database(paths.jobs_db)
    page_repository = PageRepository(database)
    job = database.get_job(job_id)
    pages = page_repository.list_pages(job_id)
    scopes = page_repository.list_scopes(job_id)
    windows = database.all_windows(job_id)
    events = database.list_events(job_id)
    conflicts = database.list_post_conflicts(job_id)

    output_dir = Path(str(job["output_dir"]))
    bundle: dict[str, Any]
    try:
        inventory = verify_export_bundle(output_dir)
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        bundle = {
            "verified": False,
            "error": redact_text(exc) or type(exc).__name__,
            "bundle_digest": None,
        }
    else:
        bundle = {
            "verified": True,
            "error": None,
            "bundle_digest": inventory.get("bundle_digest"),
            "record_counts": inventory.get("record_counts", {}),
            "coverage_status": inventory.get("bundle", {}).get("coverage_status"),
        }

    scope_states = Counter(str(scope.get("state", "UNKNOWN")) for scope in scopes)
    window_states = Counter(str(window.get("status", "UNKNOWN")) for window in windows)
    recoveries = [
        {
            "event_id": event.get("event_id"),
            "occurred_at": event.get("occurred_at"),
            "event_type": event.get("event_type"),
            "details": event.get("details", {}),
        }
        for event in events
        if str(event.get("event_type")) in _RECOVERY_EVENTS
    ]

    evidence = {
        "schema_version": _EVIDENCE_SCHEMA,
        "safe_to_share_after_manual_review": True,
        "job": {
            "job_id": job_id,
            "username": job.get("username"),
            "user_id": str(job["user_id"]) if job.get("user_id") is not None else None,
            "status": job.get("status"),
            "coverage_status": job.get("coverage_status"),
            "scope": job.get("scope"),
            "start_at": job.get("start_at"),
            "cutoff_at": job.get("cutoff_at"),
            "error_code": job.get("error_code"),
            "error_message": redact_text(job.get("error_message")),
        },
        "counts": {
            "posts": database.count_posts(job_id),
            "pages": len(pages),
            "scopes": len(scopes),
            "windows": len(windows),
            "conflicts": len(conflicts),
            "events": len(events),
        },
        "scope_states": dict(sorted(scope_states.items())),
        "window_states": dict(sorted(window_states.items())),
        "run_segments": _run_segments(events, pages),
        "recoveries": recoveries,
        "rate_limit_observed": any(
            event["event_type"] == "RATE_LIMIT_WAIT" for event in recoveries
        ),
        "bundle": bundle,
        "privacy": {
            "cookies_included": False,
            "authorization_headers_included": False,
            "raw_response_bodies_included": False,
            "cursor_values_included": False,
            "cursor_fingerprints_only": True,
        },
    }
    return redact_value(evidence)


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if os.getenv("CI") or os.getenv("GITHUB_ACTIONS"):
        raise SystemExit("W09 local evidence collection is forbidden in CI")

    paths = AppPaths.discover(args.home).ensure()
    output = args.output or paths.home / "w09-evidence" / f"{args.job_id}.json"
    reject_git_worktree_state_home(output.parent)
    evidence = build_evidence(paths.home, args.job_id)
    text = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    write_private_text(output, text)
    print(text, end="")
    print(f"W09 redacted evidence written to: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
