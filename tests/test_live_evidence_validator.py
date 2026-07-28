from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from x_scrap.live_evidence import canonical_sha256

ROOT = Path(__file__).parents[1]


def _module():
    path = ROOT / "scripts" / "live" / "validate_e2e_report.py"
    spec = importlib.util.spec_from_file_location("validate_e2e_report", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _environment():
    return {
        "python": "3.12.10",
        "python_implementation": "CPython",
        "platform": "win32",
        "x_scrap_version": "0.1.0",
        "twscrape_version": "0.19.2",
        "active_account_count": 1,
        "total_account_count": 1,
        "proxy_environment_present": False,
        "telemetry_disabled": True,
    }


def _completed(case_name: str, job_id: str = "job", *, target: str = "a" * 16):
    return {
        "schema_version": "1.1.0",
        "report_type": "x_scrap_live_e2e",
        "generated_at_utc": "2026-07-27T00:00:00Z",
        "case_name": case_name,
        "target_fingerprint": target,
        "job_id": job_id,
        "job_status": "COMPLETED",
        "coverage_status": "COMPLETE_PUBLICLY_RETRIEVABLE",
        "start_at": "2026-01-01T00:00:00Z",
        "cutoff_at": "2026-01-02T00:00:00Z",
        "completed_at": "2026-01-02T00:01:00Z",
        "counts": {
            "posts": 2,
            "pages": 2,
            "windows": 1,
            "scopes": 1,
            "conflicts": 0,
            "rate_limit_waits": 0,
            "transient_retry_wait_events": 0,
            "persisted_wait_resume_events": 0,
        },
        "coverage_summary": {
            "gaps": 0,
            "unresolved_windows": 0,
            "integrity_issues": 0,
        },
        "window_states": {"COMPLETE": 1},
        "scope_states": {"COMPLETE": 1},
        "resume_expected": False,
        "resume_observed": False,
        "resume_evidence": {
            "expected": False,
            "observed": False,
            "checkpoint_job_matches": None,
            "target_matches": None,
            "range_matches": None,
            "committed_pages_preserved": None,
            "first_new_page_used_cursor": None,
            "checkpoint_page_count": 0,
        },
        "inventory_sha256": "b" * 64,
        "bundle_digest": "c" * 64,
        "inventory_record_counts": {"posts": 2, "pages": 2},
        "inventory_source_counts": {"search": 2},
        "environment": _environment(),
        "collection_mode": "twscrape_web_graphql",
        "paid_api_calls": 0,
        "paid_proxy_calls": 0,
        "codex_calls": 0,
    }


def _checkpoint(job_id: str = "resume-job", *, target: str = "d" * 16):
    pages = [
        {
            "scope_key": "timeline:user_tweets",
            "page_index": 0,
            "payload_sha256": "e" * 64,
            "artifact_size": 100,
            "item_count": 1,
            "accepted_count": 1,
        }
    ]
    return {
        "schema_version": "1.1.0",
        "report_type": "x_scrap_live_e2e_interruption_checkpoint",
        "generated_at_utc": "2026-07-27T00:00:00Z",
        "case_name": "interruption-resume",
        "target_fingerprint": target,
        "job_id": job_id,
        "job_status": "RUNNING",
        "start_at": "2026-01-01T00:00:00Z",
        "cutoff_at": "2026-01-02T00:00:00Z",
        "page_count": 1,
        "committed_pages": pages,
        "committed_prefix_digest": canonical_sha256(pages),
        "scope_checkpoints": [
            {
                "scope_key": "timeline:user_tweets",
                "state": "RUNNING",
                "next_page_index": 1,
                "has_next_cursor": True,
                "wait_state": None,
            }
        ],
        "resumable_cursor_present": True,
        "environment": _environment(),
        "planned_interruption": True,
        "collection_mode": "twscrape_web_graphql",
        "paid_api_calls": 0,
        "paid_proxy_calls": 0,
        "codex_calls": 0,
    }


def _resumed():
    report = _completed("interruption-resume-final", "resume-job", target="d" * 16)
    report["counts"]["pages"] = 3
    report["resume_expected"] = True
    report["resume_observed"] = True
    report["resume_evidence"] = {
        "expected": True,
        "observed": True,
        "checkpoint_job_matches": True,
        "target_matches": True,
        "range_matches": True,
        "committed_pages_preserved": True,
        "first_new_page_used_cursor": True,
        "checkpoint_page_count": 1,
    }
    return report


def test_completed_live_report_validator_accepts_only_zero_paid_and_sanitized_evidence():
    assert _module().validate_report(_completed("small-fixed-range"))["status"] == "PASS"


def test_live_report_validator_rejects_nonzero_paid_usage_proxy_or_username():
    report = _completed("small-fixed-range")
    report["paid_api_calls"] = 1
    with pytest.raises(ValueError, match="paid_api_calls"):
        _module().validate_report(report)
    report["paid_api_calls"] = 0
    report["environment"]["proxy_environment_present"] = True
    with pytest.raises(ValueError, match="no proxy"):
        _module().validate_report(report)
    report["environment"]["proxy_environment_present"] = False
    report["username"] = "alice"
    with pytest.raises(ValueError, match="forbidden field"):
        _module().validate_report(report)


def test_interruption_checkpoint_validator_requires_verified_resumable_page():
    report = _checkpoint()
    assert _module().validate_report(report)["status"] == "PASS"
    report["resumable_cursor_present"] = False
    with pytest.raises(ValueError, match="resumable cursor"):
        _module().validate_report(report)


def test_acceptance_requires_all_cases_and_same_job_cursor_resume_contract():
    reports = {
        "small-fixed-range": _completed("small-fixed-range", "small-job"),
        "interruption-resume": _checkpoint(),
        "interruption-resume-final": _resumed(),
        "higher-volume": _completed("higher-volume", "volume-job", target="f" * 16),
    }
    reports["higher-volume"]["counts"]["pages"] = 4
    hashes = {name: "1" * 64 for name in reports}
    acceptance = _module().build_acceptance(reports, hashes)
    assert acceptance["status"] == "PASS"
    assert acceptance["resume_contract"]["first_new_page_used_cursor"] is True

    reports["interruption-resume-final"]["job_id"] = "wrong-job"
    with pytest.raises(ValueError, match="field job_id"):
        _module().build_acceptance(reports, hashes)


def test_acceptance_rejects_partial_coverage_or_same_id_conflict():
    reports = {
        "small-fixed-range": _completed("small-fixed-range", "small-job"),
        "interruption-resume": _checkpoint(),
        "interruption-resume-final": _resumed(),
        "higher-volume": _completed("higher-volume", "volume-job", target="f" * 16),
    }
    reports["higher-volume"]["counts"]["pages"] = 4
    hashes = {name: "2" * 64 for name in reports}
    reports["higher-volume"]["coverage_status"] = "PARTIAL_UNRESOLVED_WINDOWS"
    reports["higher-volume"]["job_status"] = "PARTIAL"
    reports["higher-volume"]["coverage_summary"]["unresolved_windows"] = 1
    with pytest.raises(ValueError, match="job_status COMPLETED"):
        _module().build_acceptance(reports, hashes)

    reports["higher-volume"] = _completed("higher-volume", "volume-job", target="f" * 16)
    reports["higher-volume"]["counts"]["pages"] = 4
    reports["higher-volume"]["counts"]["conflicts"] = 1
    with pytest.raises(ValueError, match="same-ID conflicts"):
        _module().build_acceptance(reports, hashes)
