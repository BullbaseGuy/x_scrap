from __future__ import annotations

import json

import pytest

from x_scrap.live_evidence import (
    assert_sanitized_live_evidence,
    build_environment_evidence,
    build_interruption_evidence,
    build_live_evidence,
    target_fingerprint,
    validate_case_name,
)


def _environment():
    return build_environment_evidence(
        active_accounts=1,
        total_accounts=1,
        proxy_environment_present=False,
        telemetry_disabled=True,
    )


def _result(target: str = "SensitivePublicHandle"):
    return {
        "job_id": "job-1",
        "coverage_status": "COMPLETE_PUBLICLY_RETRIEVABLE",
        "start_at": "2026-01-01T00:00:00Z",
        "cutoff_at": "2026-01-02T00:00:00Z",
        "completed_at": "2026-01-02T00:01:00Z",
        "post_count": 2,
        "page_count": 2,
        "conflict_count": 0,
        "output_dir": "C:/private/path",
        "username": target,
    }


def _coverage():
    return {
        "status": "COMPLETE_PUBLICLY_RETRIEVABLE",
        "gaps": [],
        "unresolved_windows": [],
        "integrity_issues": [],
    }


def _inventory():
    return {
        "bundle": {
            "job_id": "job-1",
            "coverage_status": "COMPLETE_PUBLICLY_RETRIEVABLE",
        },
        "bundle_digest": "b" * 64,
        "record_counts": {
            "posts": 2,
            "pages": 2,
            "windows": 1,
            "scopes": 1,
            "conflicts": 0,
        },
        "source_counts": {"search": 2},
    }


def _pages():
    return [
        {
            "scope_key": "timeline:user_tweets",
            "page_index": 0,
            "payload_sha256": "a" * 64,
            "artifact_size": 100,
            "item_count": 1,
            "accepted_count": 1,
            "request_cursor": None,
        },
        {
            "scope_key": "timeline:user_tweets",
            "page_index": 1,
            "payload_sha256": "c" * 64,
            "artifact_size": 120,
            "item_count": 1,
            "accepted_count": 1,
            "request_cursor": "opaque-resume-cursor",
        },
    ]


def test_live_evidence_contains_counts_and_hashes_but_no_target_or_private_paths(tmp_path):
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text('{"files": []}\n', encoding="utf-8")
    target = "SensitivePublicHandle"
    report = build_live_evidence(
        case_name="small-account",
        target_username=target,
        result=_result(target),
        job={"status": "COMPLETED"},
        windows=[{"status": "COMPLETE"}],
        scopes=[{"state": "COMPLETE", "rate_limit_waits": 1}],
        pages=_pages(),
        events=[],
        inventory=_inventory(),
        inventory_path=inventory_path,
        coverage=_coverage(),
        environment=_environment(),
    )

    encoded = json.dumps(report, ensure_ascii=False)
    assert target not in encoded
    assert "private/path" not in encoded
    assert "opaque-resume-cursor" not in encoded
    assert report["target_fingerprint"] == target_fingerprint(target)
    assert report["counts"]["rate_limit_waits"] == 1
    assert report["resume_observed"] is False
    assert report["paid_api_calls"] == 0


def test_interruption_and_final_evidence_prove_cursor_resume_without_exposing_cursor(tmp_path):
    target = "Alice"
    checkpoint = build_interruption_evidence(
        case_name="interruption-resume",
        target_username=target,
        job={"job_id": "job-1", "status": "RUNNING"},
        scopes=[
            {
                "scope_key": "timeline:user_tweets",
                "state": "RUNNING",
                "next_page_index": 1,
                "next_cursor": "opaque-secret-cursor",
            }
        ],
        pages=[_pages()[0]],
        start_at="2026-01-01T00:00:00Z",
        cutoff_at="2026-01-02T00:00:00Z",
        environment=_environment(),
    )
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text("{}", encoding="utf-8")
    report = build_live_evidence(
        case_name="interruption-resume-final",
        target_username=target,
        result=_result(target),
        job={"status": "COMPLETED"},
        windows=[{"status": "COMPLETE"}],
        scopes=[{"state": "COMPLETE", "rate_limit_waits": 0}],
        pages=_pages(),
        events=[{"event_type": "JOB_STARTED", "details": {"resume": True}}],
        inventory=_inventory(),
        inventory_path=inventory_path,
        coverage=_coverage(),
        environment=_environment(),
        resume_checkpoint=checkpoint,
    )

    encoded = json.dumps({"checkpoint": checkpoint, "final": report})
    assert "opaque-secret-cursor" not in encoded
    assert report["resume_observed"] is True
    assert report["resume_evidence"]["committed_pages_preserved"] is True
    assert report["resume_evidence"]["first_new_page_used_cursor"] is True


def test_live_evidence_rejects_changed_committed_page_on_resume(tmp_path):
    checkpoint = build_interruption_evidence(
        case_name="interruption-resume",
        target_username="alice",
        job={"job_id": "job-1", "status": "RUNNING"},
        scopes=[
            {
                "scope_key": "timeline:user_tweets",
                "state": "RUNNING",
                "next_page_index": 1,
                "next_cursor": "cursor",
            }
        ],
        pages=[_pages()[0]],
        start_at="2026-01-01T00:00:00Z",
        cutoff_at="2026-01-02T00:00:00Z",
        environment=_environment(),
    )
    changed = _pages()
    changed[0] = {**changed[0], "payload_sha256": "d" * 64}
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="cursor continuation contract"):
        build_live_evidence(
            case_name="interruption-resume-final",
            target_username="alice",
            result=_result("alice"),
            job={"status": "COMPLETED"},
            windows=[{"status": "COMPLETE"}],
            scopes=[{"state": "COMPLETE", "rate_limit_waits": 0}],
            pages=changed,
            events=[{"event_type": "JOB_STARTED", "details": {"resume": True}}],
            inventory=_inventory(),
            inventory_path=inventory_path,
            coverage=_coverage(),
            environment=_environment(),
            resume_checkpoint=checkpoint,
        )


def test_sanitized_evidence_rejects_forbidden_fields_credentials_and_paths():
    with pytest.raises(ValueError, match="forbidden field"):
        assert_sanitized_live_evidence({"username": "alice"})
    with pytest.raises(ValueError, match="credential-shaped"):
        assert_sanitized_live_evidence({"message": "auth_token=secret"})
    with pytest.raises(ValueError, match="private path"):
        assert_sanitized_live_evidence({"message": r"D:\\private\\accounts.db"})
    with pytest.raises(ValueError, match="private path"):
        assert_sanitized_live_evidence({"message": "/home/user/private"})


def test_case_name_rejects_target_and_path_traversal():
    assert validate_case_name("small-fixed-range", "alice") == "small-fixed-range"
    with pytest.raises(ValueError, match="1-64 ASCII"):
        validate_case_name("../escape", "alice")
    with pytest.raises(ValueError, match="must not contain"):
        validate_case_name("alice-live", "Alice")


def test_live_evidence_rejects_inventory_count_mismatch(tmp_path):
    inventory = _inventory()
    inventory["record_counts"]["pages"] = 99
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="pages count differs"):
        build_live_evidence(
            case_name="small-account",
            target_username="alice",
            result=_result("alice"),
            job={"status": "COMPLETED"},
            windows=[{"status": "COMPLETE"}],
            scopes=[{"state": "COMPLETE", "rate_limit_waits": 0}],
            pages=_pages(),
            events=[],
            inventory=inventory,
            inventory_path=inventory_path,
            coverage=_coverage(),
            environment=_environment(),
        )
