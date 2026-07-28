from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from x_scrap.adapters.twscrape_adapter import TwscrapeAdapter
from x_scrap.config import AppPaths
from x_scrap.domain.models import iso_utc, parse_datetime
from x_scrap.export.writer import verify_export_bundle
from x_scrap.live_evidence import (
    assert_sanitized_live_evidence,
    build_environment_evidence,
    build_interruption_evidence,
    build_live_evidence,
    target_fingerprint,
    validate_case_name,
)
from x_scrap.security import exception_message, write_private_text
from x_scrap.service import UserExportService
from x_scrap.storage.database import Database
from x_scrap.storage.page_repository import PageRepository

_PROXY_ENVIRONMENT_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


class PlannedLiveInterruption(BaseException):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one explicit local authenticated E2E case and write only sanitized evidence. "
            "Never run this script in GitHub Actions."
        )
    )
    parser.add_argument("--case-name", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--home", type=Path)
    parser.add_argument(
        "--resume-from-report",
        type=Path,
        help="private interruption checkpoint report produced by this tool",
    )
    parser.add_argument("--interrupt-after-pages", type=int)
    parser.add_argument("--initial-window-days", type=int, default=30)
    parser.add_argument("--min-window-seconds", type=int, default=3600)
    parser.add_argument("--max-posts-per-window", type=int, default=5000)
    parser.add_argument("--timeline-limit", type=int, default=-1)
    parser.add_argument(
        "--acknowledge-live-x",
        action="store_true",
        help="confirm that this command may contact X with the local browser session",
    )
    parser.add_argument(
        "--allow-proxy-environment",
        action="store_true",
        help="explicitly permit existing HTTP(S)/ALL_PROXY environment variables",
    )
    return parser


async def run_case(args: argparse.Namespace) -> tuple[int, dict[str, Any], Path]:
    if not args.acknowledge_live_x:
        raise ValueError("pass --acknowledge-live-x to permit an authenticated live request")
    if os.getenv("CI") or os.getenv("GITHUB_ACTIONS"):
        raise ValueError("authenticated live E2E is forbidden in CI")
    os.environ["TWS_TELEMETRY"] = "0"
    os.environ["DO_NOT_TRACK"] = "1"

    start = _required_datetime(args.start, "start")
    cutoff = _required_datetime(args.cutoff, "cutoff")
    if start >= cutoff:
        raise ValueError("start must precede cutoff")
    target_username = args.username.strip().lstrip("@").casefold()
    if not target_username:
        raise ValueError("username must not be empty")
    case_name = validate_case_name(args.case_name, target_username)
    paths = AppPaths.discover(args.home).ensure()
    evidence_dir = (paths.home / "live-evidence").resolve(strict=False)
    report_path = evidence_dir / f"{case_name}.json"

    if args.interrupt_after_pages is not None and args.resume_from_report is not None:
        raise ValueError("interruption and resume-from-report cannot be used together")
    resume_checkpoint = (
        _load_resume_checkpoint(args.resume_from_report, evidence_dir)
        if args.resume_from_report is not None
        else None
    )
    if resume_checkpoint is not None:
        _validate_checkpoint_request(
            resume_checkpoint,
            target_username=target_username,
            start_at=iso_utc(start),
            cutoff_at=iso_utc(cutoff),
        )

    adapter = TwscrapeAdapter(paths.accounts_db)
    accounts = await adapter.list_accounts()
    active_accounts = sum(bool(account.get("active")) for account in accounts)
    proxy_names = [name for name in _PROXY_ENVIRONMENT_NAMES if os.getenv(name)]
    environment = build_environment_evidence(
        active_accounts=active_accounts,
        total_accounts=len(accounts),
        proxy_environment_present=bool(proxy_names),
        telemetry_disabled=(
            os.getenv("TWS_TELEMETRY") == "0" and os.getenv("DO_NOT_TRACK") == "1"
        ),
    )
    _validate_live_environment(
        environment,
        allow_proxy_environment=args.allow_proxy_environment,
        proxy_names=proxy_names,
    )

    database = Database(paths.jobs_db)
    if resume_checkpoint is not None:
        expected_job_id = str(resume_checkpoint["job_id"])
        expected_job = database.get_job(expected_job_id)
        if expected_job["username"].casefold() != target_username:
            raise ValueError("resume checkpoint target does not match local job state")
        resumable = database.find_resumable_job(target_username)
        if resumable is None or str(resumable["job_id"]) != expected_job_id:
            raise ValueError("resume checkpoint is not the current resumable job")

    service = UserExportService(
        adapter,
        database,
        exports_root=paths.exports,
        raw_root=paths.raw,
    )
    if args.interrupt_after_pages is not None:
        if args.interrupt_after_pages < 1:
            raise ValueError("interrupt-after-pages must be positive")
        original_commit = service.pages.commit_page
        committed = 0

        def interrupting_commit(*commit_args, **commit_kwargs):
            nonlocal committed
            result = original_commit(*commit_args, **commit_kwargs)
            if result:
                committed += 1
            if committed >= args.interrupt_after_pages:
                raise PlannedLiveInterruption()
            return result

        service.pages.commit_page = interrupting_commit  # type: ignore[method-assign]

    try:
        result = await service.export_user(
            target_username,
            start=start,
            cutoff=cutoff,
            resume=resume_checkpoint is not None,
            initial_window_days=args.initial_window_days,
            min_window_seconds=args.min_window_seconds,
            max_posts_per_window=args.max_posts_per_window,
            timeline_limit=args.timeline_limit,
        )
    except PlannedLiveInterruption:
        job = database.find_resumable_job(target_username)
        if job is None:
            raise RuntimeError("planned interruption left no resumable job") from None
        pages_repo = PageRepository(database)
        report = build_interruption_evidence(
            case_name=case_name,
            target_username=target_username,
            job=job,
            scopes=pages_repo.list_scopes(job["job_id"]),
            pages=pages_repo.list_pages(job["job_id"]),
            start_at=iso_utc(start),
            cutoff_at=iso_utc(cutoff),
            environment=environment,
        )
        _write_report(report_path, report)
        return 130, report, report_path

    if resume_checkpoint is not None and str(result["job_id"]) != str(
        resume_checkpoint["job_id"]
    ):
        raise ValueError("resumed run did not reuse the checkpoint job_id")
    output_dir = Path(result["output_dir"])
    inventory = verify_export_bundle(output_dir)
    coverage = json.loads((output_dir / "coverage.json").read_text(encoding="utf-8"))
    job = database.get_job(result["job_id"])
    pages_repo = PageRepository(database)
    report = build_live_evidence(
        case_name=case_name,
        target_username=target_username,
        result=result,
        job=job,
        windows=database.all_windows(result["job_id"]),
        scopes=pages_repo.list_scopes(result["job_id"]),
        pages=pages_repo.list_pages(result["job_id"]),
        events=database.list_events(result["job_id"]),
        inventory=inventory,
        inventory_path=output_dir / "inventory.json",
        coverage=coverage,
        environment=environment,
        resume_checkpoint=resume_checkpoint,
    )
    _write_report(report_path, report)
    return 0, report, report_path


def _required_datetime(value: str, name: str):
    parsed = parse_datetime(value)
    if parsed is None or parsed.microsecond:
        raise ValueError(f"{name} must be a valid whole-second ISO-8601 timestamp")
    return parsed


def _load_resume_checkpoint(path: Path, evidence_dir: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_relative_to(evidence_dir):
        raise ValueError("resume checkpoint must be inside X_SCRAP_HOME/live-evidence")
    report = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError("resume checkpoint root must be an object")
    assert_sanitized_live_evidence(report)
    if report.get("report_type") != "x_scrap_live_e2e_interruption_checkpoint":
        raise ValueError("resume checkpoint has the wrong report type")
    return report


def _validate_checkpoint_request(
    checkpoint: dict[str, Any],
    *,
    target_username: str,
    start_at: str | None,
    cutoff_at: str | None,
) -> None:
    if checkpoint.get("target_fingerprint") != target_fingerprint(target_username):
        raise ValueError("resume checkpoint target fingerprint differs from this request")
    if checkpoint.get("start_at") != start_at or checkpoint.get("cutoff_at") != cutoff_at:
        raise ValueError("resume checkpoint range differs from this request")
    if checkpoint.get("resumable_cursor_present") is not True:
        raise ValueError("resume checkpoint did not capture a resumable cursor")


def _validate_live_environment(
    environment: dict[str, Any],
    *,
    allow_proxy_environment: bool,
    proxy_names: list[str],
) -> None:
    if sys.version_info[:2] != (3, 12):
        raise ValueError("W09 requires Python 3.12")
    if environment.get("twscrape_version") != "0.19.2":
        raise ValueError("W09 requires twscrape==0.19.2")
    if environment.get("telemetry_disabled") is not True:
        raise ValueError("W09 requires TWS_TELEMETRY=0 and DO_NOT_TRACK=1")
    if int(environment.get("active_account_count", -1)) != 1:
        raise ValueError("W09 requires exactly one active local account")
    if proxy_names and not allow_proxy_environment:
        names = ", ".join(sorted(proxy_names))
        raise ValueError(
            f"proxy environment detected ({names}); clear it or explicitly pass "
            "--allow-proxy-environment"
        )


def _write_report(path: Path, report: dict[str, Any]) -> None:
    assert_sanitized_live_evidence(report)
    write_private_text(
        path,
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def main() -> int:
    args = build_parser().parse_args()
    try:
        code, report, report_path = asyncio.run(run_case(args))
    except KeyboardInterrupt:
        print(json.dumps({"status": "INTERRUPTED"}))
        return 130
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "ERROR",
                    "error": type(exc).__name__,
                    "message": exception_message(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": "INTERRUPTED_AS_PLANNED" if code == 130 else "PASS",
                "job_id": report.get("job_id"),
                "coverage_status": report.get("coverage_status"),
                "report_file": report_path.name,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
