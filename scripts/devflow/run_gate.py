from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", choices=["repository-full", "post-merge"])
    args = parser.parse_args()
    config = json.loads(Path(".devflow/gate-profiles.json").read_text(encoding="utf-8"))
    commands = config["profiles"][args.profile]
    for command in commands:
        print("+", " ".join(command), flush=True)
        completed = subprocess.run(command, check=False)
        if completed.returncode:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
