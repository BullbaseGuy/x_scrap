from __future__ import annotations

import os
import re
import uuid
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TextIO

REDACTED = "<redacted>"
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600
_SENSITIVE_KEYS = {
    "access-token",
    "auth-token",
    "authorization",
    "cookie",
    "cookies",
    "ct0",
    "refresh-token",
    "token",
    "x-csrf-token",
}
_SECRET_PAIR_RE = re.compile(
    r"(?i)(\b(?:auth_token|ct0|access_token|refresh_token|x-csrf-token)\s*[:=]\s*)"
    r"([^;\s,'\"}&]+)"
)
_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&#](?:auth_token|ct0|access_token|refresh_token|token|authorization|cookie)=)"
    r"([^&#\s]+)"
)
_AUTH_HEADER_RE = re.compile(
    r"(?i)(\bauthorization\b[\"']?\s*[:=]\s*[\"']?)(?:bearer\s+)?([^\s,}\"']+)"
)
_COOKIE_HEADER_RE = re.compile(
    r"(?i)(\bcookie(?:s)?\b[\"']?\s*[:=]\s*[\"']?)([^\r\n}\"']+)"
)
_BEARER_RE = re.compile(r"(?i)(\bbearer\s+)([A-Za-z0-9._~+/=-]{8,})")


def redact_text(value: object | None) -> str | None:
    """Remove browser-session and authorization material from text."""

    if value is None:
        return None
    text = str(value)
    text = _SECRET_PAIR_RE.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    text = _QUERY_SECRET_RE.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    text = _AUTH_HEADER_RE.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    text = _COOKIE_HEADER_RE.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    return _BEARER_RE.sub(lambda match: f"{match.group(1)}{REDACTED}", text)


def redact_value(value: Any, *, key: str | None = None) -> Any:
    """Recursively redact sensitive keys and credential-shaped strings."""

    normalized_key = key.lower().replace("_", "-") if key is not None else None
    if normalized_key in _SENSITIVE_KEYS:
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(item_key): redact_value(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, set):
        return sorted((redact_value(item) for item in value), key=str)
    return value


def exception_message(exc: BaseException) -> str:
    return redact_text(str(exc)) or type(exc).__name__


def resolved_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def find_containing_git_worktree(path: str | Path) -> Path | None:
    """Find a conventional Git worktree containing an existing or future path."""

    candidate = resolved_path(path)
    for ancestor in (candidate, *candidate.parents):
        marker = ancestor / ".git"
        if marker.is_dir() or marker.is_file():
            return ancestor
    return None


def reject_git_worktree_state_home(path: str | Path) -> Path:
    resolved = resolved_path(path)
    worktree = find_containing_git_worktree(resolved)
    if worktree is not None:
        raise ValueError(
            "X_SCRAP_HOME must be outside a Git worktree; "
            f"refusing state path under {worktree}"
        )
    return resolved


def assert_outside_git_worktree(path: str | Path) -> None:
    reject_git_worktree_state_home(path)


def ensure_private_directory(path: str | Path) -> Path:
    target = resolved_path(path)
    if target.exists() and target.is_symlink():
        raise ValueError(f"private directory cannot be a symbolic link: {target}")
    target.mkdir(mode=_PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
    secure_directory(target)
    return target


def secure_directory(path: str | Path) -> None:
    target = Path(path)
    if os.name == "posix" and target.exists():
        if target.is_symlink():
            raise ValueError(f"private directory cannot be a symbolic link: {target}")
        target.chmod(_PRIVATE_DIRECTORY_MODE)


def secure_file(path: str | Path) -> None:
    target = Path(path)
    if os.name == "posix" and target.exists():
        if target.is_symlink():
            raise ValueError(f"private file cannot be a symbolic link: {target}")
        target.chmod(_PRIVATE_FILE_MODE)


def protect_private_file(path: str | Path) -> None:
    secure_file(path)


def secure_sqlite_family(path: str | Path) -> None:
    database = Path(path)
    for candidate in (
        database,
        Path(f"{database}-wal"),
        Path(f"{database}-shm"),
        Path(f"{database}-journal"),
    ):
        secure_file(candidate)


def protect_sqlite_files(path: str | Path) -> None:
    secure_sqlite_family(path)


@contextmanager
def private_text_writer(
    path: str | Path,
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
):
    """Atomically replace a private text file after a successful write."""

    target = Path(path)
    ensure_private_directory(target.parent)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    descriptor: int | None = None
    handle: TextIO | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            _PRIVATE_FILE_MODE,
        )
        handle = os.fdopen(descriptor, "w", encoding=encoding, newline=newline)
        descriptor = None
        yield handle
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        handle = None
        os.replace(temporary, target)
        secure_file(target)
    finally:
        if handle is not None:
            handle.close()
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def open_private_text(
    path: str | Path,
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
) -> TextIO:
    target = Path(path)
    ensure_private_directory(target.parent)
    descriptor = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        _PRIVATE_FILE_MODE,
    )
    secure_file(target)
    return os.fdopen(descriptor, "w", encoding=encoding, newline=newline)


def write_private_text(
    path: str | Path,
    text: str,
    *,
    encoding: str = "utf-8",
) -> None:
    with private_text_writer(path, encoding=encoding, newline="") as handle:
        handle.write(text)


def atomic_write_private_bytes(path: str | Path, data: bytes) -> None:
    target = Path(path)
    ensure_private_directory(target.parent)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            _PRIVATE_FILE_MODE,
        )
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        secure_file(target)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def atomic_write_private_text(
    path: str | Path,
    text: str,
    *,
    encoding: str = "utf-8",
) -> None:
    atomic_write_private_bytes(path, text.encode(encoding))


def secure_existing_tree(root: str | Path) -> None:
    target = Path(root)
    if not target.exists():
        return
    secure_directory(target)
    for path in target.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_dir():
            secure_directory(path)
        elif path.is_file():
            secure_file(path)


def is_within(path: str | Path, root: str | Path) -> bool:
    candidate = resolved_path(path)
    boundary = resolved_path(root)
    return candidate == boundary or boundary in candidate.parents


def require_relative_path(relative: Path) -> None:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe relative path: {relative}")


def redact_sequence(values: Sequence[Any]) -> list[Any]:
    return [redact_value(value) for value in values]
