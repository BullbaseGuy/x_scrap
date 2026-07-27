from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
    def discover(cls, home: str | Path | None = None) -> "AppPaths":
        return cls(Path(home).expanduser() if home else _default_home())

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

    def ensure(self) -> "AppPaths":
        self.home.mkdir(parents=True, exist_ok=True)
        self.exports.mkdir(parents=True, exist_ok=True)
        self.raw.mkdir(parents=True, exist_ok=True)
        return self
