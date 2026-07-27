from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from x_scrap.security import (
    ensure_private_directory,
    private_text_writer,
    redact_value,
    secure_existing_tree,
    write_private_text,
)

_REQUIRED_PAYLOAD_FILES = {
    "manifest.json",
    "profile.json",
    "coverage.json",
    "tweets.jsonl",
    "tweets.csv",
    "errors.jsonl",
    "conflicts.jsonl",
    "summary.md",
}
_ERROR_MARKERS = (
    "AUTH",
    "ERROR",
    "FAIL",
    "INTERRUPT",
    "RECOVERABLE",
    "SCHEMA",
    "SUSPECT",
    "UNAVAILABLE",
)


def write_export(
    output_dir: Path,
    *,
    manifest: dict[str, Any],
    profile: dict[str, Any],
    coverage: dict[str, Any],
    posts: Iterable[dict[str, Any]],
    events: Iterable[dict[str, Any]] = (),
    conflicts: Iterable[dict[str, Any]] = (),
    scopes: Iterable[dict[str, Any]] = (),
    windows: Iterable[dict[str, Any]] = (),
    pages: Iterable[dict[str, Any]] = (),
    raw_root: Path | None = None,
) -> dict[str, Any]:
    """Build, verify, and atomically publish one immutable-style export bundle."""

    output_dir = output_dir.expanduser().resolve(strict=False)
    parent = ensure_private_directory(output_dir.parent)
    staging = ensure_private_directory(
        parent / f".{output_dir.name}.staging-{uuid.uuid4().hex}"
    )
    try:
        inventory = _write_staging_bundle(
            staging,
            manifest=manifest,
            profile=profile,
            coverage=coverage,
            posts=list(posts),
            events=list(events),
            conflicts=list(conflicts),
            scopes=list(scopes),
            windows=list(windows),
            pages=list(pages),
            raw_root=raw_root,
        )
        verified = verify_export_bundle(staging)
        if verified["bundle_digest"] != inventory["bundle_digest"]:
            raise ValueError("staged export inventory digest changed during verification")
        _publish_bundle(staging, output_dir, inventory["bundle_digest"])
        secure_existing_tree(output_dir)
        return inventory
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def verify_export_bundle(output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve(strict=False)
    inventory_path = output_dir / "inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if inventory.get("schema_version") != "1.0.0":
        raise ValueError("unsupported export inventory schema")
    listed = {str(entry.get("path")) for entry in inventory.get("files", [])}
    if listed != _REQUIRED_PAYLOAD_FILES:
        raise ValueError("export inventory does not list the required payload files")

    for entry in inventory["files"]:
        relative = Path(str(entry["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe export inventory path: {relative}")
        path = output_dir / relative
        data = path.read_bytes()
        if len(data) != int(entry["size"]):
            raise ValueError(f"export size mismatch: {relative}")
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError(f"export hash mismatch: {relative}")
        expected_records = entry.get("record_count")
        if expected_records is not None:
            actual_records = _record_count(path, data)
            if actual_records != int(expected_records):
                raise ValueError(f"export record count mismatch: {relative}")

    jsonl_posts = _jsonl_posts(output_dir / "tweets.jsonl")
    jsonl_ids = [str(row["post_id"]) for row in jsonl_posts]
    csv_ids = _csv_post_ids(output_dir / "tweets.csv")
    if jsonl_ids != csv_ids:
        raise ValueError("tweets JSONL and CSV identities differ")
    if jsonl_posts != sorted(
        jsonl_posts,
        key=lambda row: (str(row.get("created_at", "")), str(row["post_id"])),
    ):
        raise ValueError("tweets are not in stable created-at/post-id order")

    digest_payload = {key: value for key, value in inventory.items() if key != "bundle_digest"}
    digest = hashlib.sha256(_canonical_json_bytes(digest_payload)).hexdigest()
    if digest != inventory.get("bundle_digest"):
        raise ValueError("export inventory bundle digest mismatch")
    return inventory


def _write_staging_bundle(
    staging: Path,
    *,
    manifest: dict[str, Any],
    profile: dict[str, Any],
    coverage: dict[str, Any],
    posts: list[dict[str, Any]],
    events: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    scopes: list[dict[str, Any]],
    windows: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    raw_root: Path | None,
) -> dict[str, Any]:
    normalized_posts = [_normalized_post(post) for post in posts]
    normalized_posts.sort(key=lambda row: (str(row.get("created_at", "")), str(row["post_id"])))
    normalized_conflicts = sorted(
        (redact_value(row) for row in conflicts),
        key=lambda row: (
            str(row.get("post_id", "")),
            str(row.get("observed_source", "")),
            str(row.get("observed_material_sha256", "")),
        ),
    )
    normalized_events = [redact_value(row) for row in events]
    error_events = [
        row
        for row in normalized_events
        if any(marker in str(row.get("event_type", "")).upper() for marker in _ERROR_MARKERS)
    ]

    file_records: dict[str, int | None] = {}
    _write_json(staging / "manifest.json", manifest)
    file_records["manifest.json"] = 1
    _write_json(staging / "profile.json", profile)
    file_records["profile.json"] = 1
    _write_json(staging / "coverage.json", coverage)
    file_records["coverage.json"] = 1
    _write_jsonl(staging / "tweets.jsonl", normalized_posts)
    file_records["tweets.jsonl"] = len(normalized_posts)
    _write_csv(staging / "tweets.csv", normalized_posts)
    file_records["tweets.csv"] = len(normalized_posts)
    _write_jsonl(staging / "errors.jsonl", error_events)
    file_records["errors.jsonl"] = len(error_events)
    _write_jsonl(staging / "conflicts.jsonl", normalized_conflicts)
    file_records["conflicts.jsonl"] = len(normalized_conflicts)
    write_private_text(staging / "summary.md", _summary(manifest, coverage, len(normalized_conflicts)))
    file_records["summary.md"] = None

    entries = []
    for relative in sorted(_REQUIRED_PAYLOAD_FILES):
        path = staging / relative
        data = path.read_bytes()
        entries.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "record_count": file_records[relative],
            }
        )

    source_counts = Counter(
        str(source)
        for post in normalized_posts
        for source in post.get("sources", [])
    )
    scope_summaries = _scope_summaries(scopes, pages)
    window_summaries = [
        {
            "window_id": row.get("window_id"),
            "start_at": row.get("start_at"),
            "end_at": row.get("end_at"),
            "depth": row.get("depth"),
            "status": row.get("status"),
            "post_count": row.get("post_count"),
            "terminal_reason": row.get("terminal_reason"),
        }
        for row in sorted(
            windows,
            key=lambda row: (
                str(row.get("start_at", "")),
                int(row.get("depth", 0)),
                str(row.get("window_id", "")),
            ),
        )
    ]
    raw_evidence = _raw_evidence(pages, raw_root)
    inventory: dict[str, Any] = {
        "schema_version": "1.0.0",
        "bundle": {
            "job_id": manifest.get("job_id"),
            "username": manifest.get("username"),
            "start_at": manifest.get("start_at"),
            "cutoff_at": manifest.get("cutoff_at"),
            "coverage_status": coverage.get("status"),
        },
        "schemas": {
            "manifest": manifest.get("schema_version"),
            "coverage": coverage.get("schema_version"),
            "inventory": "1.0.0",
        },
        "record_counts": {
            "posts": len(normalized_posts),
            "errors": len(error_events),
            "conflicts": len(normalized_conflicts),
            "events": len(normalized_events),
            "scopes": len(scopes),
            "windows": len(windows),
            "pages": len(pages),
            "raw_artifacts": len(raw_evidence),
        },
        "source_counts": dict(sorted(source_counts.items())),
        "scope_summaries": scope_summaries,
        "window_summaries": window_summaries,
        "raw_evidence": raw_evidence,
        "known_source_limitations": list(coverage.get("known_source_limitations", [])),
        "files": entries,
    }
    inventory["bundle_digest"] = hashlib.sha256(_canonical_json_bytes(inventory)).hexdigest()
    _write_json(staging / "inventory.json", inventory)
    return inventory


def _publish_bundle(staging: Path, output_dir: Path, bundle_digest: str) -> None:
    if output_dir.exists():
        try:
            existing = verify_export_bundle(output_dir)
        except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            existing = None
        if existing is not None and existing.get("bundle_digest") == bundle_digest:
            return
        backup = output_dir.with_name(f".{output_dir.name}.backup-{uuid.uuid4().hex}")
        os.replace(output_dir, backup)
        try:
            os.replace(staging, output_dir)
        except Exception:
            os.replace(backup, output_dir)
            raise
        shutil.rmtree(backup)
        return
    os.replace(staging, output_dir)


def _normalized_post(post: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(post)
    post_id = normalized.get("post_id")
    if not isinstance(post_id, str) or not post_id:
        raise ValueError("exported post IDs must be non-empty strings")
    created_at = normalized.get("created_at")
    if not isinstance(created_at, str) or not created_at.endswith("Z"):
        raise ValueError(f"exported post {post_id} must use a UTC Z timestamp")
    normalized["sources"] = sorted({str(source) for source in normalized.get("sources", [])})
    return normalized


def _write_json(path: Path, value: Any) -> None:
    write_private_text(path, _pretty_json_text(value))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with private_text_writer(path, encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                    default=str,
                )
                + "\n"
            )


def _write_csv(path: Path, posts: list[dict[str, Any]]) -> None:
    fields = [
        "post_id",
        "created_at",
        "username",
        "text",
        "url",
        "conversation_id",
        "in_reply_to_post_id",
        "quoted_post_id",
        "reposted_post_id",
        "language",
        "is_reply",
        "is_quote",
        "is_retweet",
        "sources",
    ]
    with private_text_writer(path, encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for post in posts:
            row = dict(post)
            row["sources"] = ",".join(post.get("sources", []))
            writer.writerow(row)


def _scope_summaries(
    scopes: list[dict[str, Any]], pages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    page_counts: dict[str, int] = defaultdict(int)
    item_counts: dict[str, int] = defaultdict(int)
    accepted_counts: dict[str, int] = defaultdict(int)
    for page in pages:
        key = str(page.get("scope_key"))
        page_counts[key] += 1
        item_counts[key] += int(page.get("item_count", 0))
        accepted_counts[key] += int(page.get("accepted_count", 0))
    return [
        {
            "scope_key": row.get("scope_key"),
            "source": row.get("source"),
            "state": row.get("state"),
            "next_page_index": row.get("next_page_index"),
            "has_next_cursor": row.get("next_cursor") is not None,
            "page_count": page_counts[str(row.get("scope_key"))],
            "item_count": item_counts[str(row.get("scope_key"))],
            "accepted_observation_count": accepted_counts[str(row.get("scope_key"))],
        }
        for row in sorted(scopes, key=lambda row: str(row.get("scope_key", "")))
    ]


def _raw_evidence(
    pages: list[dict[str, Any]], raw_root: Path | None
) -> list[dict[str, Any]]:
    root = raw_root.expanduser().resolve(strict=False) if raw_root is not None else None
    evidence: list[dict[str, Any]] = []
    for page in sorted(
        pages,
        key=lambda row: (str(row.get("scope_key", "")), int(row.get("page_index", 0))),
    ):
        path = Path(str(page.get("artifact_path", ""))).resolve(strict=False)
        try:
            relative = path.relative_to(root).as_posix() if root is not None else path.name
        except ValueError:
            relative = "<outside-raw-root>"
        evidence.append(
            {
                "scope_key": page.get("scope_key"),
                "page_index": page.get("page_index"),
                "path": relative,
                "sha256": page.get("payload_sha256"),
                "size": page.get("artifact_size"),
            }
        )
    return evidence


def _summary(
    manifest: dict[str, Any], coverage: dict[str, Any], conflict_count: int
) -> str:
    return f"""# X user export summary

- Job: `{manifest['job_id']}`
- User: `@{manifest['username']}`
- Posts: **{manifest['post_count']}**
- Pages: **{manifest.get('page_count', 0)}**
- Coverage: `{coverage['status']}`
- Integrity: `{coverage.get('integrity', {}).get('status', 'NOT_CHECKED')}`
- Source conflicts: **{conflict_count}**
- Start: `{manifest['start_at']}`
- Cutoff: `{manifest['cutoff_at']}`

## Interpretation

The coverage status refers to content publicly retrievable through the configured X account and current search index at collection time. It does not claim recovery of deleted, protected, suspended, de-indexed, or otherwise unavailable posts. Validate `inventory.json` before treating the bundle as complete.
"""


def _pretty_json_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=str,
    ) + "\n"


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")


def _record_count(path: Path, data: bytes) -> int:
    if path.suffix == ".jsonl":
        return sum(bool(line.strip()) for line in data.decode("utf-8").splitlines())
    if path.suffix == ".csv":
        return max(0, len(list(csv.reader(data.decode("utf-8-sig").splitlines()))) - 1)
    return 1


def _jsonl_posts(path: Path) -> list[dict[str, Any]]:
    posts: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            post_id = value.get("post_id")
            if not isinstance(post_id, str):
                raise ValueError("tweets JSONL contains a non-string post ID")
            posts.append(value)
    return posts


def _csv_post_ids(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [str(row["post_id"]) for row in csv.DictReader(handle)]
