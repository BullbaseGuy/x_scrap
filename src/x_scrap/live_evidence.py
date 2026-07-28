from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
from collections import Counter
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from x_scrap.domain.models import iso_utc, utc_now
from x_scrap.security import redact_value

_CASE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{16}$")
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_PRIVATE_POSIX_PREFIXES = ("/home/", "/users/", "/mnt/", "/private/", "/var/folders/")
_FORBIDDEN_REPORT_KEYS = {
    "username",
    "requested_username",
    "target_username",
    "screen_name",
    "output_dir",
    "artifact_path",
    "cookie",
    "cookies",
    "auth_token",
    "ct0",
    "authorization",
    "account_label",
    "account_labels",
    "proxy",
    "proxy_url",
    "raw_payload",
    "raw_content",
    "full_text",
    "text",
    "description",
    "profile_url",
    "url",
    "request_cursor",
    "next_cursor",
}


def package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "not-installed"


def target_fingerprint(username: str) -> str:
    normalized = username.strip().lstrip("@").casefold()
    if not normalized:
        raise ValueError("target username must not be empty")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def validate_case_name(case_name: str, target_username: str | None = None) -> str:
    normalized = case_name.strip()
    if not _CASE_NAME_RE.fullmatch(normalized) or normalized in {".", ".."}:
        raise ValueError(
            "case_name must be 1-64 ASCII letters, digits, dot, underscore, or hyphen"
        )
    target = (target_username or "").strip().lstrip("@").casefold()
    if target and target in normalized.casefold():
        raise ValueError("case_name must not contain the target username")
    return normalized


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_environment_evidence(
    *,
    active_accounts: int,
    total_accounts: int,
    proxy_environment_present: bool,
    telemetry_disabled: bool,
) -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": sys.platform,
        "x_scrap_version": package_version("x-scrap"),
        "twscrape_version": package_version("twscrape"),
        "active_account_count": active_accounts,
        "total_account_count": total_accounts,
        "proxy_environment_present": proxy_environment_present,
        "telemetry_disabled": telemetry_disabled,
    }


def safe_page_evidence(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence = [
        {
            "scope_key": str(page.get("scope_key", "")),
            "page_index": int(page.get("page_index", -1)),
            "payload_sha256": str(page.get("payload_sha256", "")),
            "artifact_size": int(page.get("artifact_size", -1)),
            "item_count": int(page.get("item_count", -1)),
            "accepted_count": int(page.get("accepted_count", -1)),
        }
        for page in pages
    ]
    evidence.sort(key=lambda row: (row["scope_key"], row["page_index"]))
    for row in evidence:
        if not row["scope_key"] or row["page_index"] < 0:
            raise ValueError("page evidence is missing a valid scope key or page index")
        if not _SHA256_RE.fullmatch(row["payload_sha256"]):
            raise ValueError("page evidence contains an invalid payload SHA-256")
        if row["artifact_size"] < 0 or row["item_count"] < 0 or row["accepted_count"] < 0:
            raise ValueError("page evidence contains a negative count or size")
    return evidence


def build_live_evidence(
    *,
    case_name: str,
    target_username: str,
    result: dict[str, Any],
    job: dict[str, Any],
    windows: list[dict[str, Any]],
    scopes: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    events: list[dict[str, Any]],
    inventory: dict[str, Any],
    inventory_path: Path,
    coverage: dict[str, Any],
    environment: dict[str, Any],
    resume_checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_name = validate_case_name(case_name, target_username)
    event_types = Counter(str(event.get("event_type", "")) for event in events)
    window_states = Counter(str(window.get("status", "")) for window in windows)
    scope_states = Counter(str(scope.get("state", "")) for scope in scopes)
    _require_inventory_consistency(
        result=result,
        windows=windows,
        scopes=scopes,
        pages=pages,
        inventory=inventory,
        coverage=coverage,
    )

    resume_evidence = _resume_evidence(
        target_username=target_username,
        result=result,
        scopes=scopes,
        pages=pages,
        events=events,
        checkpoint=resume_checkpoint,
    )
    report = {
        "schema_version": "1.1.0",
        "report_type": "x_scrap_live_e2e",
        "generated_at_utc": iso_utc(utc_now()),
        "case_name": safe_name,
        "target_fingerprint": target_fingerprint(target_username),
        "job_id": str(result["job_id"]),
        "job_status": str(job["status"]),
        "coverage_status": str(result["coverage_status"]),
        "start_at": result["start_at"],
        "cutoff_at": result["cutoff_at"],
        "completed_at": result.get("completed_at"),
        "counts": {
            "posts": int(result["post_count"]),
            "pages": len(pages),
            "windows": len(windows),
            "scopes": len(scopes),
            "conflicts": int(result.get("conflict_count", 0)),
            "rate_limit_waits": sum(
                int(scope.get("rate_limit_waits") or 0) for scope in scopes
            ),
            "transient_retry_wait_events": event_types["TRANSIENT_RETRY_WAIT"],
            "persisted_wait_resume_events": event_types["PERSISTED_WAIT_RESUMED"],
        },
        "coverage_summary": {
            "gaps": len(coverage.get("gaps", [])),
            "unresolved_windows": len(coverage.get("unresolved_windows", [])),
            "integrity_issues": len(coverage.get("integrity_issues", [])),
        },
        "window_states": dict(sorted(window_states.items())),
        "scope_states": dict(sorted(scope_states.items())),
        "resume_expected": resume_checkpoint is not None,
        "resume_observed": resume_evidence["observed"],
        "resume_evidence": resume_evidence,
        "inventory_sha256": file_sha256(inventory_path),
        "bundle_digest": str(inventory.get("bundle_digest", "")),
        "inventory_record_counts": inventory.get("record_counts", {}),
        "inventory_source_counts": inventory.get("source_counts", {}),
        "environment": environment,
        "collection_mode": "twscrape_web_graphql",
        "paid_api_calls": 0,
        "paid_proxy_calls": 0,
        "codex_calls": 0,
    }
    sanitized = redact_value(report)
    assert_sanitized_live_evidence(sanitized)
    return sanitized


def build_interruption_evidence(
    *,
    case_name: str,
    target_username: str,
    job: dict[str, Any],
    scopes: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    start_at: str,
    cutoff_at: str,
    environment: dict[str, Any],
) -> dict[str, Any]:
    safe_name = validate_case_name(case_name, target_username)
    committed_pages = safe_page_evidence(pages)
    checkpoints = [
        {
            "scope_key": str(scope.get("scope_key", "")),
            "state": str(scope.get("state", "")),
            "next_page_index": int(scope.get("next_page_index") or 0),
            "has_next_cursor": scope.get("next_cursor") is not None,
            "wait_state": scope.get("state")
            if scope.get("state") in {"WAITING_RATE_LIMIT", "WAITING_RETRY"}
            else None,
        }
        for scope in scopes
    ]
    checkpoints.sort(key=lambda row: row["scope_key"])
    report = {
        "schema_version": "1.1.0",
        "report_type": "x_scrap_live_e2e_interruption_checkpoint",
        "generated_at_utc": iso_utc(utc_now()),
        "case_name": safe_name,
        "target_fingerprint": target_fingerprint(target_username),
        "job_id": str(job["job_id"]),
        "job_status": str(job["status"]),
        "start_at": start_at,
        "cutoff_at": cutoff_at,
        "page_count": len(committed_pages),
        "committed_pages": committed_pages,
        "committed_prefix_digest": canonical_sha256(committed_pages),
        "scope_checkpoints": checkpoints,
        "resumable_cursor_present": any(
            checkpoint["has_next_cursor"] for checkpoint in checkpoints
        ),
        "environment": environment,
        "planned_interruption": True,
        "collection_mode": "twscrape_web_graphql",
        "paid_api_calls": 0,
        "paid_proxy_calls": 0,
        "codex_calls": 0,
    }
    sanitized = redact_value(report)
    assert_sanitized_live_evidence(sanitized)
    return sanitized


def assert_sanitized_live_evidence(value: Any) -> None:
    def walk(item: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                normalized = str(key).casefold()
                if normalized in _FORBIDDEN_REPORT_KEYS:
                    raise ValueError(
                        f"live evidence contains forbidden field: {'.'.join((*path, str(key)))}"
                    )
                walk(child, (*path, str(key)))
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, (*path, str(index)))
        elif isinstance(item, str):
            lowered = item.casefold()
            if "auth_token=" in lowered or "ct0=" in lowered or "bearer " in lowered:
                raise ValueError("live evidence contains credential-shaped material")
            if _WINDOWS_ABSOLUTE_RE.match(item) or lowered.startswith(_PRIVATE_POSIX_PREFIXES):
                raise ValueError("live evidence contains an absolute private path")

    walk(value)
    json.dumps(value, ensure_ascii=False, sort_keys=True)


def valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def valid_target_fingerprint(value: Any) -> bool:
    return isinstance(value, str) and _FINGERPRINT_RE.fullmatch(value) is not None


def _require_inventory_consistency(
    *,
    result: dict[str, Any],
    windows: list[dict[str, Any]],
    scopes: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    inventory: dict[str, Any],
    coverage: dict[str, Any],
) -> None:
    record_counts = inventory.get("record_counts")
    if not isinstance(record_counts, dict):
        raise ValueError("verified inventory is missing record_counts")
    expected = {
        "posts": int(result["post_count"]),
        "pages": len(pages),
        "windows": len(windows),
        "scopes": len(scopes),
        "conflicts": int(result.get("conflict_count", 0)),
    }
    for key, value in expected.items():
        if int(record_counts.get(key, -1)) != value:
            raise ValueError(f"inventory {key} count differs from committed database state")
    bundle = inventory.get("bundle")
    if not isinstance(bundle, dict):
        raise ValueError("verified inventory is missing bundle metadata")
    if str(bundle.get("job_id")) != str(result["job_id"]):
        raise ValueError("inventory job_id differs from completed result")
    if str(bundle.get("coverage_status")) != str(coverage.get("status")):
        raise ValueError("inventory and coverage statuses differ")
    if str(result.get("coverage_status")) != str(coverage.get("status")):
        raise ValueError("result and coverage statuses differ")
    if not valid_sha256(inventory.get("bundle_digest")):
        raise ValueError("verified inventory bundle digest is invalid")


def _resume_evidence(
    *,
    target_username: str,
    result: dict[str, Any],
    scopes: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    events: list[dict[str, Any]],
    checkpoint: dict[str, Any] | None,
) -> dict[str, Any]:
    event_resume = any(
        event.get("event_type") == "JOB_STARTED"
        and isinstance(event.get("details"), dict)
        and event["details"].get("resume") is True
        for event in events
    ) or any(event.get("event_type") == "PERSISTED_WAIT_RESUMED" for event in events)
    if checkpoint is None:
        return {
            "expected": False,
            "observed": event_resume,
            "checkpoint_job_matches": None,
            "target_matches": None,
            "range_matches": None,
            "committed_pages_preserved": None,
            "first_new_page_used_cursor": None,
            "checkpoint_page_count": 0,
        }

    assert_sanitized_live_evidence(checkpoint)
    if checkpoint.get("report_type") != "x_scrap_live_e2e_interruption_checkpoint":
        raise ValueError("resume checkpoint has the wrong report type")
    expected_fingerprint = target_fingerprint(target_username)
    checkpoint_pages = checkpoint.get("committed_pages")
    if not isinstance(checkpoint_pages, list):
        raise ValueError("resume checkpoint is missing committed_pages")
    safe_checkpoint_pages = safe_page_evidence(checkpoint_pages)
    if canonical_sha256(safe_checkpoint_pages) != checkpoint.get("committed_prefix_digest"):
        raise ValueError("resume checkpoint committed page digest is invalid")

    final_pages = safe_page_evidence(pages)
    by_key = {
        (row["scope_key"], row["page_index"]): row
        for row in final_pages
    }
    committed_pages_preserved = all(
        by_key.get((row["scope_key"], row["page_index"])) == row
        for row in safe_checkpoint_pages
    )
    raw_pages = {
        (str(row.get("scope_key", "")), int(row.get("page_index", -1))): row
        for row in pages
    }
    checkpoint_scopes = checkpoint.get("scope_checkpoints")
    if not isinstance(checkpoint_scopes, list):
        raise ValueError("resume checkpoint is missing scope_checkpoints")
    resumable = [row for row in checkpoint_scopes if row.get("has_next_cursor") is True]
    first_new_page_used_cursor = bool(resumable) and all(
        (
            (str(row.get("scope_key", "")), int(row.get("next_page_index", -1)))
            in raw_pages
            and raw_pages[
                (str(row.get("scope_key", "")), int(row.get("next_page_index", -1)))
            ].get("request_cursor")
            is not None
        )
        for row in resumable
    )
    range_matches = (
        checkpoint.get("start_at") == result.get("start_at")
        and checkpoint.get("cutoff_at") == result.get("cutoff_at")
    )
    job_matches = str(checkpoint.get("job_id")) == str(result.get("job_id"))
    target_matches = checkpoint.get("target_fingerprint") == expected_fingerprint
    observed = all(
        (
            event_resume,
            job_matches,
            target_matches,
            range_matches,
            committed_pages_preserved,
            first_new_page_used_cursor,
        )
    )
    if not observed:
        raise ValueError("resume evidence did not prove the committed cursor continuation contract")
    return {
        "expected": True,
        "observed": True,
        "checkpoint_job_matches": job_matches,
        "target_matches": target_matches,
        "range_matches": range_matches,
        "committed_pages_preserved": committed_pages_preserved,
        "first_new_page_used_cursor": first_new_page_used_cursor,
        "checkpoint_page_count": len(safe_checkpoint_pages),
    }
