from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from pathlib import Path

from x_scrap.cli import main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Explicit local authenticated smoke test. This command refuses CI and never "
            "accepts credentials as arguments."
        )
    )
    parser.add_argument("username", nargs="?")
    parser.add_argument("--home", type=Path)
    parser.add_argument("--start")
    parser.add_argument("--cutoff")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--initial-window-days", type=int, default=30)
    parser.add_argument("--min-window-seconds", type=int, default=3600)
    parser.add_argument("--max-posts-per-window", type=int, default=5000)
    parser.add_argument("--timeline-limit", type=int, default=-1)
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="list redacted local account state without making an X request",
    )
    parser.add_argument(
        "--acknowledge-live-x",
        action="store_true",
        help="confirm this run will contact X using the locally stored browser session",
    )
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if os.getenv("CI") or os.getenv("GITHUB_ACTIONS"):
        raise SystemExit("live X smoke tests are forbidden in CI")

    prefix: list[str] = []
    if args.home is not None:
        prefix.extend(["--home", str(args.home)])
    if args.preflight_only:
        return main([*prefix, "auth", "list"])
    if not args.username:
        raise SystemExit("username is required unless --preflight-only is used")
    if not args.acknowledge_live_x:
        raise SystemExit("pass --acknowledge-live-x to permit an authenticated live request")

    command = [*prefix, "user", "export", "--username", args.username]
    for flag, value in (
        ("--start", args.start),
        ("--cutoff", args.cutoff),
    ):
        if value:
            command.extend([flag, value])
    if args.no_resume:
        command.append("--no-resume")
    command.extend(
        [
            "--initial-window-days",
            str(args.initial_window_days),
            "--min-window-seconds",
            str(args.min_window_seconds),
            "--max-posts-per-window",
            str(args.max_posts_per_window),
            "--timeline-limit",
            str(args.timeline_limit),
        ]
    )
    return main(command)


if __name__ == "__main__":
    raise SystemExit(run())
