from __future__ import annotations

import argparse

from x_scrap.cli import main


def run() -> int:
    parser = argparse.ArgumentParser(
        description="Explicit local authenticated smoke test; never run this in GitHub Actions."
    )
    parser.add_argument("username")
    parser.add_argument("--start")
    parser.add_argument("--cutoff")
    args = parser.parse_args()
    argv = ["user", "export", "--username", args.username]
    if args.start:
        argv.extend(["--start", args.start])
    if args.cutoff:
        argv.extend(["--cutoff", args.cutoff])
    return main(argv)


if __name__ == "__main__":
    raise SystemExit(run())
