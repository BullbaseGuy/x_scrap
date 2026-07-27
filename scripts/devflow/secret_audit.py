from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

EXCLUDED_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".gz", ".db"}
FORBIDDEN_NAMES = {".env", "accounts.db", "jobs.db"}
PATTERNS = {
    "github_token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "x_auth_token_value": re.compile(r"auth_token\s*=\s*(?!\.\.\.|<|x{3,}|\*)[A-Za-z0-9%_-]{20,}", re.I),
    "x_ct0_value": re.compile(r"ct0\s*=\s*(?!\.\.\.|<|y{3,}|\*)[A-Za-z0-9%_-]{20,}", re.I),
}


def iter_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        if path.name in FORBIDDEN_NAMES or path.name.startswith(".env."):
            yield path, "FORBIDDEN_FILE"
            continue
        try:
            yield path, path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


def audit(root: Path) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    for path, content in iter_text_files(root):
        relative = path.relative_to(root).as_posix()
        if content == "FORBIDDEN_FILE":
            findings.append({"path": relative, "line": 0, "kind": "forbidden_file"})
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            for kind, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append({"path": relative, "line": line_number, "kind": kind})
    return {"status": "PASS" if not findings else "FAIL", "findings": findings}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("devflow-secret-result.json"))
    args = parser.parse_args()
    result = audit(args.root.resolve())
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
