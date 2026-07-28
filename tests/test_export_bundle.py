from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from x_scrap.export.writer import verify_export_bundle, write_export


def _payloads():
    manifest = {
        "schema_version": "2.0.0",
        "job_id": "job-1",
        "username": "alice",
        "requested_username": "alice",
        "user_id": "7",
        "start_at": "2026-01-01T00:00:00Z",
        "cutoff_at": "2026-01-02T00:00:00Z",
        "post_count": 2,
        "page_count": 0,
        "conflict_count": 0,
        "coverage_status": "COMPLETE_PUBLICLY_RETRIEVABLE",
        "completed_at": "2026-01-02T00:01:00Z",
        "collector": "x_scrap",
        "adapter": "FixtureAdapter",
    }
    profile = {
        "user_id": "7",
        "username": "alice",
        "captured_at": "2026-01-01T00:00:00Z",
    }
    coverage = {
        "schema_version": "2.0.0",
        "status": "COMPLETE_PUBLICLY_RETRIEVABLE",
        "integrity": {"status": "PASS", "error_count": 0, "errors": []},
        "known_source_limitations": ["fixture limitation"],
    }
    posts = [
        {
            "post_id": "2",
            "created_at": "2026-01-01T02:00:00Z",
            "username": "alice",
            "text": "中文 two",
            "url": "https://x.com/alice/status/2",
            "conversation_id": "2",
            "in_reply_to_post_id": None,
            "quoted_post_id": None,
            "reposted_post_id": None,
            "language": "zh",
            "is_reply": False,
            "is_quote": False,
            "is_retweet": False,
            "sources": ["search", "user_tweets"],
        },
        {
            "post_id": "1",
            "created_at": "2026-01-01T01:00:00Z",
            "username": "alice",
            "text": "first",
            "url": "https://x.com/alice/status/1",
            "conversation_id": "1",
            "in_reply_to_post_id": None,
            "quoted_post_id": None,
            "reposted_post_id": None,
            "language": "en",
            "is_reply": False,
            "is_quote": False,
            "is_retweet": False,
            "sources": ["search"],
        },
    ]
    events = [
        {
            "event_id": 1,
            "occurred_at": "2026-01-01T00:00:00Z",
            "event_type": "AUTH_ERROR",
            "details": {
                "message": "authorization: Bearer secret-token-value auth_token=supersecretvalue; ct0=csrfsecretvalue"
            },
        }
    ]
    return manifest, profile, coverage, posts, events


def _write(path: Path):
    manifest, profile, coverage, posts, events = _payloads()
    return write_export(
        path,
        manifest=manifest,
        profile=profile,
        coverage=coverage,
        posts=posts,
        events=events,
    )


def test_export_bundle_is_reproducible_self_verifying_sorted_and_redacted(tmp_path):
    first = _write(tmp_path / "one")
    second = _write(tmp_path / "two")

    assert first == second
    assert verify_export_bundle(tmp_path / "one") == first
    assert [
        json.loads(line)["post_id"]
        for line in (tmp_path / "one" / "tweets.jsonl").read_text(encoding="utf-8").splitlines()
    ] == ["1", "2"]
    errors = (tmp_path / "one" / "errors.jsonl").read_text(encoding="utf-8")
    assert "supersecretvalue" not in errors
    assert "csrfsecretvalue" not in errors
    assert "secret-token-value" not in errors
    assert "<redacted>" in errors

    tweets_path = tmp_path / "one" / "tweets.jsonl"
    original = tweets_path.read_bytes()
    replacement = (b"X" if original[:1] != b"X" else b"Y") + original[1:]
    tweets_path.write_bytes(replacement)
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_export_bundle(tmp_path / "one")


def test_failed_staging_build_does_not_replace_existing_bundle(tmp_path):
    output = tmp_path / "bundle"
    existing = _write(output)
    manifest, profile, coverage, posts, events = _payloads()
    invalid = deepcopy(posts)
    invalid[0]["post_id"] = 2

    with pytest.raises(ValueError, match="IDs must be non-empty strings"):
        write_export(
            output,
            manifest=manifest,
            profile=profile,
            coverage=coverage,
            posts=invalid,
            events=events,
        )

    assert verify_export_bundle(output)["bundle_digest"] == existing["bundle_digest"]
    assert not list(output.parent.glob(f".{output.name}.staging-*"))
