from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from x_scrap.domain.models import JobStatus, PostRecord, TimeWindow, WindowStatus, iso_utc, utc_now


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    user_id TEXT,
                    status TEXT NOT NULL,
                    coverage_status TEXT,
                    scope TEXT NOT NULL,
                    start_at TEXT,
                    cutoff_at TEXT NOT NULL,
                    output_dir TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_resume
                    ON jobs(username, status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS windows (
                    window_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                    source TEXT NOT NULL,
                    start_at TEXT NOT NULL,
                    end_at TEXT NOT NULL,
                    depth INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    post_count INTEGER NOT NULL DEFAULT 0,
                    oldest_post_at TEXT,
                    newest_post_at TEXT,
                    terminal_reason TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(job_id, source, start_at, end_at)
                );
                CREATE INDEX IF NOT EXISTS idx_windows_pending
                    ON windows(job_id, status, start_at);

                CREATE TABLE IF NOT EXISTS posts (
                    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                    post_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    username TEXT NOT NULL,
                    source_set TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(job_id, post_id)
                );
                CREATE INDEX IF NOT EXISTS idx_posts_export
                    ON posts(job_id, created_at, post_id);

                CREATE TABLE IF NOT EXISTS user_snapshots (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
                    payload TEXT NOT NULL,
                    captured_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                    occurred_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details TEXT NOT NULL
                );
                """
            )

    def create_job(
        self,
        *,
        username: str,
        cutoff_at: datetime,
        scope: str,
        output_dir: Path,
        start_at: datetime | None = None,
    ) -> str:
        job_id = utc_now().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        now = iso_utc(utc_now())
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO jobs
                (job_id, username, status, scope, start_at, cutoff_at, output_dir, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    username.lstrip("@"),
                    JobStatus.PENDING.value,
                    scope,
                    iso_utc(start_at),
                    iso_utc(cutoff_at),
                    str(output_dir),
                    now,
                    now,
                ),
            )
        return job_id

    def find_resumable_job(self, username: str) -> dict[str, Any] | None:
        statuses = (
            JobStatus.PENDING.value,
            JobStatus.RUNNING.value,
            JobStatus.WAITING_RATE_LIMIT.value,
            JobStatus.PARTIAL.value,
        )
        placeholders = ",".join("?" for _ in statuses)
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT * FROM jobs WHERE username=? AND status IN ({placeholders}) ORDER BY updated_at DESC LIMIT 1",
                (username.lstrip("@"), *statuses),
            ).fetchone()
        return dict(row) if row else None

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        return dict(row)

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def update_job(self, job_id: str, **changes: Any) -> None:
        allowed = {
            "user_id",
            "status",
            "coverage_status",
            "start_at",
            "error_code",
            "error_message",
        }
        invalid = set(changes) - allowed
        if invalid:
            raise ValueError(f"unsupported job fields: {sorted(invalid)}")
        if not changes:
            return
        changes["updated_at"] = iso_utc(utc_now())
        assignments = ", ".join(f"{key}=?" for key in changes)
        values = [value.value if hasattr(value, "value") else value for value in changes.values()]
        with self.connect() as conn:
            conn.execute(
                f"UPDATE jobs SET {assignments} WHERE job_id=?", (*values, job_id)
            )

    def save_user_snapshot(self, job_id: str, payload: dict[str, Any]) -> None:
        captured_at = payload.get("captured_at") or iso_utc(utc_now())
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO user_snapshots(job_id, payload, captured_at)
                VALUES (?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET payload=excluded.payload, captured_at=excluded.captured_at""",
                (job_id, json.dumps(payload, ensure_ascii=False, sort_keys=True), captured_at),
            )

    def get_user_snapshot(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload FROM user_snapshots WHERE job_id=?", (job_id,)
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def add_windows(self, job_id: str, source: str, windows: list[TimeWindow]) -> None:
        now = iso_utc(utc_now())
        with self.connect() as conn:
            for window in windows:
                conn.execute(
                    """INSERT OR IGNORE INTO windows
                    (window_id, job_id, source, start_at, end_at, depth, status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        f"{source}:{window.key}",
                        job_id,
                        source,
                        iso_utc(window.start),
                        iso_utc(window.end),
                        window.depth,
                        WindowStatus.PENDING.value,
                        now,
                    ),
                )

    def pending_windows(self, job_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM windows WHERE job_id=? AND status IN (?, ?, ?)
                ORDER BY start_at, depth""",
                (
                    job_id,
                    WindowStatus.PENDING.value,
                    WindowStatus.RUNNING.value,
                    WindowStatus.FAILED.value,
                ),
            ).fetchall()
        return [dict(row) for row in rows]

    def all_windows(self, job_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM windows WHERE job_id=? ORDER BY start_at, depth", (job_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def update_window(self, window_id: str, **changes: Any) -> None:
        allowed = {
            "status",
            "attempts",
            "post_count",
            "oldest_post_at",
            "newest_post_at",
            "terminal_reason",
        }
        invalid = set(changes) - allowed
        if invalid:
            raise ValueError(f"unsupported window fields: {sorted(invalid)}")
        changes["updated_at"] = iso_utc(utc_now())
        assignments = ", ".join(f"{key}=?" for key in changes)
        values = [value.value if hasattr(value, "value") else value for value in changes.values()]
        with self.connect() as conn:
            conn.execute(
                f"UPDATE windows SET {assignments} WHERE window_id=?", (*values, window_id)
            )

    def upsert_post(self, job_id: str, post: PostRecord) -> bool:
        now = iso_utc(utc_now())
        payload = post.to_json()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT source_set FROM posts WHERE job_id=? AND post_id=?",
                (job_id, post.post_id),
            ).fetchone()
            if existing:
                sources = set(json.loads(existing["source_set"]))
                sources.add(post.source)
                conn.execute(
                    """UPDATE posts SET source_set=?, payload=?, updated_at=?
                    WHERE job_id=? AND post_id=?""",
                    (json.dumps(sorted(sources)), payload, now, job_id, post.post_id),
                )
                return False
            conn.execute(
                """INSERT INTO posts
                (job_id, post_id, created_at, username, source_set, payload, first_seen_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    post.post_id,
                    iso_utc(post.created_at),
                    post.username,
                    json.dumps([post.source]),
                    payload,
                    now,
                    now,
                ),
            )
            return True

    def iter_posts(self, job_id: str) -> Iterator[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT payload, source_set FROM posts WHERE job_id=? ORDER BY created_at, post_id",
                (job_id,),
            ).fetchall()
        for row in rows:
            payload = json.loads(row["payload"])
            payload["sources"] = json.loads(row["source_set"])
            yield payload

    def count_posts(self, job_id: str) -> int:
        with self.connect() as conn:
            return int(
                conn.execute("SELECT COUNT(*) FROM posts WHERE job_id=?", (job_id,)).fetchone()[0]
            )

    def add_event(self, job_id: str, event_type: str, details: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO events(job_id, occurred_at, event_type, details) VALUES (?, ?, ?, ?)",
                (
                    job_id,
                    iso_utc(utc_now()),
                    event_type,
                    json.dumps(details, ensure_ascii=False, sort_keys=True, default=str),
                ),
            )
