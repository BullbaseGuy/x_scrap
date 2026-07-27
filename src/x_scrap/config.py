from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from x_scrap.security import (
    ensure_private_directory,
    reject_git_worktree_state_home,
    resolved_path,
    secure_existing_tree,
    secure_sqlite_family,
)


def _default_home() -> Path:
    override = os.getenv("X_SCRAP_HOME")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
        if base:
            return Path(base) / "x_scrap"
    return Path.home() / ".local" / "share" / "x_scrap"


@dataclass(frozen=True, slots=True)
class AppPaths:
    home: Path

    @classmethod
    def discover(cls, home: str | Path | None = None) -> AppPaths:
        return cls(resolved_path(home or _default_home()))

    @property
    def accounts_db(self) -> Path:
        return self.home / "accounts.db"

    @property
    def jobs_db(self) -> Path:
        return self.home / "jobs.db"

    @property
    def exports(self) -> Path:
        return self.home / "exports"

    @property
    def raw(self) -> Path:
        return self.home / "raw"

    def ensure(self) -> AppPaths:
        reject_git_worktree_state_home(self.home)
        ensure_private_directory(self.home)
        ensure_private_directory(self.exports)
        ensure_private_directory(self.raw)
        self.secure_runtime_files()
        return self

    def secure_runtime_files(self) -> None:
        secure_sqlite_family(self.accounts_db)
        secure_sqlite_family(self.jobs_db)
        secure_existing_tree(self.exports)
        secure_existing_tree(self.raw)
