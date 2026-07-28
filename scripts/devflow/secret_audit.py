from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

EXCLUDED_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".gz"}
FORBIDDEN_DIRS = {"captures", "exports", "raw", "secrets", "x_scrap_data", ".x_scrap"}
FORBIDDEN_NAMES = {".env", "accounts.db", "jobs.db", "cookie.txt", "cookies.txt"}
FORBIDDEN_SUFFIXES = {".db", ".har", ".sqlite", ".sqlite3"}
PATTERNS = {
    "github_token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "x_auth_token_value": re.compile(
        r"auth_token\s*=\s*(?!\.\.\.|<|x{3,}|example|redacted|\*)[A-Za-z0-9%_-]{20,}",
        re.I,
    ),
    "x_ct0_value": re.compile(
        r"ct0\s*=\s*(?!\.\.\.|<|y{3,}|example|redacted|\*)[A-Za-z0-9%_-]{20,}",
        re.I,
    ),
    "authorization_value": re.compile(
        r"authorization\s*[:=]\s*(?:bearer\s+)?(?!<|example|redacted)[A-Za-z0-9._~+/=-]{20,}",
        re.I,
    ),
    "sensitive_query_value": re.compile(
        r"[?&](?:auth_token|ct0|access_token|refresh_token|token)="
        r"(?!\.\.\.|<|example|redacted)[^&#\s]{20,}",
        re.I,
    ),
}


def _forbidden_reason(path: Path, root: Path) -> str | None:
    relative = path.relative_to(root)
    lowered_parts = {part.lower() for part in relative.parts[:-1]}
    if lowered_parts & FORBIDDEN_DIRS:
        return "forbidden_data_directory"
    name = path.name.lower()
    if name in FORBIDDEN_NAMES or name.startswith(".env."):
        return "forbidden_file"
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        return "forbidden_data_file"
    if name.endswith((".db-wal", ".db-shm", ".db-journal", ".sqlite-wal", ".sqlite-shm")):
        return "forbidden_sqlite_sidecar"
    if name.startswith(("cookie-", "cookies-")) and name.endswith(".txt"):
        return "forbidden_cookie_file"
    return None


def iter_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        reason = _forbidden_reason(path, root)
        if reason is not None:
            yield path, reason
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        try:
            yield path, path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


def audit(root: Path) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    for path, content in iter_text_files(root):
        relative = path.relative_to(root).as_posix()
        if content.startswith("forbidden_"):
            findings.append({"path": relative, "line": 0, "kind": content})
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
