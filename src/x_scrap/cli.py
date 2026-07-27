from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from x_scrap.adapters.twscrape_adapter import TwscrapeAdapter
from x_scrap.config import AppPaths
from x_scrap.domain.models import parse_datetime
from x_scrap.security import redact_text, redact_value
from x_scrap.service import UserExportService
from x_scrap.storage.database import Database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="x-scrap")
    parser.add_argument("--home", type=Path, help="local state directory; defaults to X_SCRAP_HOME")
    sub = parser.add_subparsers(dest="command", required=True)

    auth = sub.add_parser("auth", help="manage local X browser-cookie sessions")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    add_cookie = auth_sub.add_parser("add-cookie")
    add_cookie.add_argument("--label", required=True)
    auth_sub.add_parser("list")

    user = sub.add_parser("user")
    user_sub = user.add_subparsers(dest="user_command", required=True)
    export = user_sub.add_parser("export")
    export.add_argument("--username", required=True)
    export.add_argument("--start", help="inclusive ISO-8601 UTC timestamp")
    export.add_argument("--cutoff", help="exclusive ISO-8601 UTC timestamp; fixed at start by default")
    export.add_argument("--no-resume", action="store_true")
    export.add_argument("--include-retweets", action="store_true")
    export.add_argument("--initial-window-days", type=int, default=30)
    export.add_argument("--min-window-seconds", type=int, default=3600)
    export.add_argument("--max-posts-per-window", type=int, default=5000)
    export.add_argument("--timeline-limit", type=int, default=-1)

    jobs = sub.add_parser("jobs")
    jobs_sub = jobs.add_subparsers(dest="jobs_command", required=True)
    jobs_list = jobs_sub.add_parser("list")
    jobs_list.add_argument("--limit", type=int, default=20)
    jobs_show = jobs_sub.add_parser("show")
    jobs_show.add_argument("job_id")
    return parser


async def _run(args: argparse.Namespace) -> int:
    paths = AppPaths.discover(args.home).ensure()
    db = Database(paths.jobs_db)
    if args.command == "jobs":
        payload = db.list_jobs(args.limit) if args.jobs_command == "list" else db.get_job(args.job_id)
        print(json.dumps(redact_value(payload), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    adapter = TwscrapeAdapter(paths.accounts_db)
    if args.command == "auth":
        if args.auth_command == "add-cookie":
            cookie = getpass.getpass("Paste auth_token and ct0 cookie header: ")
            await adapter.add_cookie(args.label, cookie)
            print(json.dumps({"status": "ADDED", "label": args.label}))
        else:
            print(json.dumps(redact_value(await adapter.list_accounts()), ensure_ascii=False, indent=2))
        return 0

    if args.command == "user" and args.user_command == "export":
        service = UserExportService(
            adapter,
            db,
            exports_root=paths.exports,
            raw_root=paths.raw,
        )
        result = await service.export_user(
            args.username,
            start=_parse_cli_datetime(args.start),
            cutoff=_parse_cli_datetime(args.cutoff),
            resume=not args.no_resume,
            include_retweets=args.include_retweets,
            initial_window_days=args.initial_window_days,
            min_window_seconds=args.min_window_seconds,
            max_posts_per_window=args.max_posts_per_window,
            timeline_limit=args.timeline_limit,
        )
        print(json.dumps(redact_value(result), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return 2


def _parse_cli_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise SystemExit(f"invalid ISO-8601 datetime: {value}")
    return parsed.astimezone(UTC)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print(json.dumps({"status": "INTERRUPTED"}), file=sys.stderr)
        return 130
    except Exception as exc:
        payload = {
            "status": "ERROR",
            "error": type(exc).__name__,
            "message": redact_text(exc),
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
