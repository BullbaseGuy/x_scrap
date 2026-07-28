from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from x_scrap.domain.models import iso_utc, parse_datetime, utc_now
from x_scrap.live_evidence import (
    assert_sanitized_live_evidence,
    canonical_sha256,
    file_sha256,
    safe_page_evidence,
    valid_sha256,
    valid_target_fingerprint,
    validate_case_name,
)
from x_scrap.security import write_private_text

_ALLOWED_TYPES = {
    "x_scrap_live_e2e",
    "x_scrap_live_e2e_interruption_checkpoint",
}
_REQUIRED_CASES = {
    "small-fixed-range",
    "interruption-resume",
    "interruption-resume-final",
    "higher-volume",
}
_REQUIRED_ZERO_METRICS = ("paid_api_calls", "paid_proxy_calls", "codex_calls")


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    assert_sanitized_live_evidence(report)
    if report.get("schema_version") != "1.1.0":
        raise ValueError("unsupported live evidence schema_version")
    report_type = report.get("report_type")
    if report_type not in _ALLOWED_TYPES:
        raise ValueError(f"unsupported live evidence report_type: {report_type!r}")
    case_name = validate_case_name(str(report.get("case_name", "")))
    if not valid_target_fingerprint(report.get("target_fingerprint")):
        raise ValueError("live evidence target_fingerprint is invalid")
    if not isinstance(report.get("job_id"), str) or not report["job_id"].strip():
        raise ValueError("live evidence job_id is missing")
    _require_utc_timestamp(report.get("generated_at_utc"), "generated_at_utc")
    _require_utc_timestamp(report.get("start_at"), "start_at")
    _require_utc_timestamp(report.get("cutoff_at"), "cutoff_at")
    if parse_datetime(report["start_at"]) >= parse_datetime(report["cutoff_at"]):
        raise ValueError("live evidence start_at must precede cutoff_at")

    environment = report.get("environment")
    if not isinstance(environment, dict):
        raise ValueError("live evidence environment must be an object")
    if not str(environment.get("python", "")).startswith("3.12."):
        raise ValueError("live evidence must use Python 3.12")
    if environment.get("twscrape_version") != "0.19.2":
        raise ValueError("live evidence must use twscrape==0.19.2")
    if int(environment.get("active_account_count", -1)) != 1:
        raise ValueError("live evidence must record exactly one active account")
    if environment.get("telemetry_disabled") is not True:
        raise ValueError("live evidence must prove upstream telemetry was disabled")
    if environment.get("proxy_environment_present") is not False:
        raise ValueError("automatic W09 acceptance requires no proxy environment")
    if report.get("collection_mode") != "twscrape_web_graphql":
        raise ValueError("live evidence collection_mode is invalid")
    for key in _REQUIRED_ZERO_METRICS:
        if int(report.get(key, -1)) != 0:
            raise ValueError(f"live evidence {key} must equal zero")

    if report_type == "x_scrap_live_e2e":
        _validate_completed_report(report)
    else:
        _validate_interruption_report(report)

    return {
        "status": "PASS",
        "report_type": report_type,
        "case_name": case_name,
        "job_id": report.get("job_id"),
        "coverage_status": report.get("coverage_status"),
        "resume_observed": report.get("resume_observed"),
    }


def build_acceptance(reports: dict[str, dict[str, Any]], report_hashes: dict[str, str]) -> dict[str, Any]:
    if set(reports) != _REQUIRED_CASES:
        missing = sorted(_REQUIRED_CASES - set(reports))
        unexpected = sorted(set(reports) - _REQUIRED_CASES)
        raise ValueError(f"W09 case set mismatch; missing={missing}, unexpected={unexpected}")
    for report in reports.values():
        validate_report(report)

    small = reports["small-fixed-range"]
    interrupted = reports["interruption-resume"]
    resumed = reports["interruption-resume-final"]
    volume = reports["higher-volume"]
    if interrupted["report_type"] != "x_scrap_live_e2e_interruption_checkpoint":
        raise ValueError("interruption-resume must be an interruption checkpoint")
    for name, report in (
        ("small-fixed-range", small),
        ("interruption-resume-final", resumed),
        ("higher-volume", volume),
    ):
        if report["report_type"] != "x_scrap_live_e2e":
            raise ValueError(f"{name} must be a completed live report")
        if report.get("job_status") != "COMPLETED":
            raise ValueError(f"{name} must finish with job_status COMPLETED")
        if report.get("coverage_status") != "COMPLETE_PUBLICLY_RETRIEVABLE":
            raise ValueError(f"{name} must finish with complete observable-source coverage")
        counts = report["counts"]
        if int(counts.get("conflicts", -1)) != 0:
            raise ValueError(f"{name} contains unresolved same-ID conflicts")
        summary = report["coverage_summary"]
        if any(int(summary.get(key, -1)) != 0 for key in summary):
            raise ValueError(f"{name} contains unresolved coverage or integrity findings")

    if int(small["counts"].get("pages", 0)) < 1:
        raise ValueError("small-fixed-range must commit at least one page")
    if int(volume["counts"].get("pages", 0)) < 2:
        raise ValueError("higher-volume must commit at least two pages")
    if int(volume["counts"].get("windows", 0)) < 1:
        raise ValueError("higher-volume must traverse at least one historical window")

    for key in ("job_id", "target_fingerprint", "start_at", "cutoff_at"):
        if interrupted.get(key) != resumed.get(key):
            raise ValueError(f"resume final report differs from checkpoint field {key}")
    resume = resumed.get("resume_evidence")
    if not isinstance(resume, dict) or not all(
        resume.get(key) is True
        for key in (
            "expected",
            "observed",
            "checkpoint_job_matches",
            "target_matches",
            "range_matches",
            "committed_pages_preserved",
            "first_new_page_used_cursor",
        )
    ):
        raise ValueError("resume final report did not prove the complete cursor-resume contract")
    if int(resumed["counts"].get("pages", 0)) <= int(interrupted.get("page_count", 0)):
        raise ValueError("resumed run did not commit a page after the interruption checkpoint")

    report_rows = []
    for name in sorted(_REQUIRED_CASES):
        report = reports[name]
        row = {
            "case_name": name,
            "report_sha256": report_hashes[name],
            "report_type": report["report_type"],
            "job_id": report["job_id"],
            "target_fingerprint": report["target_fingerprint"],
        }
        if report["report_type"] == "x_scrap_live_e2e":
            row.update(
                {
                    "coverage_status": report["coverage_status"],
                    "bundle_digest": report["bundle_digest"],
                    "inventory_sha256": report["inventory_sha256"],
                    "counts": report["counts"],
                }
            )
        else:
            row.update(
                {
                    "page_count": report["page_count"],
                    "committed_prefix_digest": report["committed_prefix_digest"],
                }
            )
        report_rows.append(row)

    acceptance = {
        "schema_version": "1.0.0",
        "report_type": "x_scrap_w09_acceptance",
        "generated_at_utc": iso_utc(utc_now()),
        "status": "PASS",
        "reports": report_rows,
        "resume_contract": {
            "job_id": resumed["job_id"],
            "checkpoint_page_count": interrupted["page_count"],
            "final_page_count": resumed["counts"]["pages"],
            "committed_pages_preserved": True,
            "first_new_page_used_cursor": True,
        },
        "rate_limit_observed": any(
            int(report.get("counts", {}).get("rate_limit_waits", 0)) > 0
            for report in (small, resumed, volume)
        ),
        "paid_api_calls": 0,
        "paid_proxy_calls": 0,
        "codex_calls": 0,
    }
    assert_sanitized_live_evidence(acceptance)
    return acceptance


def _validate_completed_report(report: dict[str, Any]) -> None:
    if report.get("job_status") not in {"COMPLETED", "PARTIAL"}:
        raise ValueError("completed live evidence has an invalid job_status")
    if report.get("coverage_status") not in {
        "COMPLETE_PUBLICLY_RETRIEVABLE",
        "PARTIAL_UNRESOLVED_WINDOWS",
        "SOURCE_CONFLICT",
    }:
        raise ValueError("completed live evidence has an invalid coverage_status")
    _require_utc_timestamp(report.get("completed_at"), "completed_at")
    if not valid_sha256(report.get("inventory_sha256")):
        raise ValueError("completed live evidence inventory_sha256 is invalid")
    if not valid_sha256(report.get("bundle_digest")):
        raise ValueError("completed live evidence bundle_digest is invalid")
    counts = report.get("counts")
    required_counts = {
        "posts",
        "pages",
        "windows",
        "scopes",
        "conflicts",
        "rate_limit_waits",
        "transient_retry_wait_events",
        "persisted_wait_resume_events",
    }
    if not isinstance(counts, dict) or not required_counts.issubset(counts):
        raise ValueError("completed live evidence counts are incomplete")
    if any(int(counts[key]) < 0 for key in required_counts):
        raise ValueError("completed live evidence counts must be nonnegative")
    coverage_summary = report.get("coverage_summary")
    if not isinstance(coverage_summary, dict) or set(coverage_summary) != {
        "gaps",
        "unresolved_windows",
        "integrity_issues",
    }:
        raise ValueError("completed live evidence coverage_summary is invalid")
    if any(int(value) < 0 for value in coverage_summary.values()):
        raise ValueError("coverage_summary counts must be nonnegative")
    resume_expected = report.get("resume_expected") is True
    resume = report.get("resume_evidence")
    if not isinstance(resume, dict) or resume.get("expected") is not resume_expected:
        raise ValueError("completed live evidence resume metadata is inconsistent")
    if resume_expected and report.get("resume_observed") is not True:
        raise ValueError("expected resume was not observed")


def _validate_interruption_report(report: dict[str, Any]) -> None:
    if report.get("planned_interruption") is not True:
        raise ValueError("interruption checkpoint must be explicitly planned")
    page_count = int(report.get("page_count", -1))
    if page_count < 1:
        raise ValueError("interruption checkpoint must contain at least one committed page")
    pages = report.get("committed_pages")
    if not isinstance(pages, list) or len(pages) != page_count:
        raise ValueError("interruption checkpoint committed page count is inconsistent")
    safe_pages = safe_page_evidence(pages)
    if not valid_sha256(report.get("committed_prefix_digest")):
        raise ValueError("interruption checkpoint committed_prefix_digest is invalid")
    if canonical_sha256(safe_pages) != report["committed_prefix_digest"]:
        raise ValueError("interruption checkpoint committed page digest does not verify")
    if report.get("resumable_cursor_present") is not True:
        raise ValueError("interruption checkpoint did not preserve a resumable cursor")
    checkpoints = report.get("scope_checkpoints")
    if not isinstance(checkpoints, list) or not any(
        checkpoint.get("has_next_cursor") is True for checkpoint in checkpoints
    ):
        raise ValueError("interruption checkpoint is missing a resumable Scope")


def _require_utc_timestamp(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{name} must be a UTC Z timestamp")
    parsed = parse_datetime(value)
    if parsed is None or parsed.microsecond:
        raise ValueError(f"{name} must be a valid whole-second UTC timestamp")


def _load_reports(
    paths: list[Path],
) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    reports: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    summaries: list[dict[str, Any]] = []
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError(f"report root must be an object: {path.name}")
        summary = validate_report(report)
        case_name = str(summary["case_name"])
        if case_name in reports:
            raise ValueError(f"duplicate W09 case_name: {case_name}")
        reports[case_name] = report
        hashes[case_name] = file_sha256(path)
        summaries.append({"file": path.name, **summary})
    return reports, hashes, summaries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance-output", type=Path)
    parser.add_argument("reports", type=Path, nargs="+")
    args = parser.parse_args()
    try:
        resolved = [path.expanduser().resolve(strict=True) for path in args.reports]
        reports, hashes, summaries = _load_reports(resolved)
        response: dict[str, Any] = {"status": "PASS", "reports": summaries}
        if args.acceptance_output is not None:
            parents = {path.parent for path in resolved}
            if len(parents) != 1:
                raise ValueError("all W09 reports must share one private evidence directory")
            output = args.acceptance_output.expanduser().resolve(strict=False)
            if output.parent not in parents:
                raise ValueError("acceptance output must share the reports' private directory")
            acceptance = build_acceptance(reports, hashes)
            write_private_text(
                output,
                json.dumps(acceptance, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
            response["acceptance"] = {
                "status": "PASS",
                "file": output.name,
                "sha256": file_sha256(output),
                "rate_limit_observed": acceptance["rate_limit_observed"],
            }
    except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(response, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
