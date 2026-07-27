from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _module():
    path = ROOT / "scripts" / "live" / "run_e2e_case.py"
    spec = importlib.util.spec_from_file_location("run_e2e_case", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _checkpoint():
    return {
        "schema_version": "1.1.0",
        "report_type": "x_scrap_live_e2e_interruption_checkpoint",
        "case_name": "interruption-resume",
        "target_fingerprint": "2bd806c97f0e00af",
        "job_id": "job",
        "start_at": "2026-01-01T00:00:00Z",
        "cutoff_at": "2026-01-02T00:00:00Z",
        "resumable_cursor_present": True,
        "planned_interruption": True,
    }


def test_parser_requires_explicit_live_acknowledgement_at_runtime():
    args = _module().build_parser().parse_args(
        [
            "--case-name",
            "small-fixed-range",
            "--username",
            "alice",
            "--start",
            "2026-01-01T00:00:00Z",
            "--cutoff",
            "2026-01-02T00:00:00Z",
        ]
    )
    assert args.acknowledge_live_x is False


def test_resume_checkpoint_must_be_inside_private_evidence_directory(tmp_path):
    module = _module()
    evidence = tmp_path / "private" / "live-evidence"
    evidence.mkdir(parents=True)
    inside = evidence / "checkpoint.json"
    inside.write_text(json.dumps(_checkpoint()), encoding="utf-8")
    assert module._load_resume_checkpoint(inside, evidence)["job_id"] == "job"

    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_checkpoint()), encoding="utf-8")
    with pytest.raises(ValueError, match="inside X_SCRAP_HOME"):
        module._load_resume_checkpoint(outside, evidence)


def test_checkpoint_request_must_match_target_range_and_resumable_cursor():
    module = _module()
    checkpoint = _checkpoint()
    module._validate_checkpoint_request(
        checkpoint,
        target_username="alice",
        start_at="2026-01-01T00:00:00Z",
        cutoff_at="2026-01-02T00:00:00Z",
    )
    checkpoint["cutoff_at"] = "2026-01-03T00:00:00Z"
    with pytest.raises(ValueError, match="range differs"):
        module._validate_checkpoint_request(
            checkpoint,
            target_username="alice",
            start_at="2026-01-01T00:00:00Z",
            cutoff_at="2026-01-02T00:00:00Z",
        )


def test_live_environment_requires_pinned_runtime_and_explicit_proxy_ack(monkeypatch):
    module = _module()
    monkeypatch.setattr(module.sys, "version_info", (3, 12, 10))
    environment = {
        "twscrape_version": "0.19.2",
        "telemetry_disabled": True,
        "active_account_count": 1,
    }
    module._validate_live_environment(
        environment,
        allow_proxy_environment=False,
        proxy_names=[],
    )
    with pytest.raises(ValueError, match="proxy environment"):
        module._validate_live_environment(
            environment,
            allow_proxy_environment=False,
            proxy_names=["HTTPS_PROXY"],
        )
    module._validate_live_environment(
        environment,
        allow_proxy_environment=True,
        proxy_names=["HTTPS_PROXY"],
    )


def test_windows_orchestrator_uses_no_echo_cookie_path_and_all_four_cases():
    source = (ROOT / "scripts" / "live" / "run_w09.ps1").read_text(encoding="utf-8")
    assert "--cookie" not in source
    assert "auth add-cookie --label primary" in source
    for case_name in (
        "small-fixed-range",
        "interruption-resume",
        "interruption-resume-final",
        "higher-volume",
    ):
        assert case_name in source
    assert "--resume-from-report" in source
    assert "W09_ACCEPTANCE.json" in source
