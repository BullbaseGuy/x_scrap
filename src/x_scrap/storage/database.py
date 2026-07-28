from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from x_scrap.domain.models import (
    JobStatus,
    PostRecord,
    TimeWindow,
    WindowStatus,
    iso_utc,
    post_material_payload,
    post_material_sha256,
    utc_now,
)
from x_scrap.security import (
    ensure_private_directory,
    redact_text,
    redact_value,
    secure_sqlite_family,
)


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve(strict=False)
        ensure_private_directory(self.path.parent)
        self.initialize()
        secure_sqlite_family(self.path)

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
            secure_sqlite_family(self.path)

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

                CREATE TABLE IF NOT EXISTS post_conflicts (
                    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                    post_id TEXT NOT NULL,
                    canonical_material_sha256 TEXT NOT NULL,
                    observed_material_sha256 TEXT NOT NULL,
                    observed_source TEXT NOT NULL,
                    canonical_material TEXT NOT NULL,
                    observed_material TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    PRIMARY KEY(
                        job_id, post_id, canonical_material_sha256,
                        observed_material_sha256, observed_source
                    ),
                    FOREIGN KEY(job_id, post_id)
                        REFERENCES posts(job_id, post_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_post_conflicts_job
                    ON post_conflicts(job_id, post_id);

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
        return redact_value(dict(row)) if row else None

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        return redact_value(dict(row))

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [redact_value(dict(row)) for row in rows]

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
        for key in ("error_code", "error_message"):
            if key in changes:
                changes[key] = redact_text(changes[key])
        changes["updated_at"] = iso_utc(utc_now())
        assignments = ", ".join(f"{key}=?" for key in changes)
        values = [value.value if hasattr(value, "value") else value for value in changes.values()]
        with self.connect() as conn:
            conn.execute(
                f"UPDATE jobs SET {assignments} WHERE job_id=?", (*values, job_id)
            )

    def save_user_snapshot(self, job_id: str, payload: dict[str, Any]) -> None:
        payload = redact_value(payload)
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
        if "terminal_reason" in changes:
            changes["terminal_reason"] = redact_text(changes["terminal_reason"])
        changes["updated_at"] = iso_utc(utc_now())
        assignments = ", ".join(f"{key}=?" for key in changes)
        values = [value.value if hasattr(value, "value") else value for value in changes.values()]
        with self.connect() as conn:
            conn.execute(
                f"UPDATE windows SET {assignments} WHERE window_id=?", (*values, window_id)
            )

    def upsert_post(self, job_id: str, post: PostRecord) -> bool:
        now = iso_utc(utc_now())
        with self.connect() as conn:
            inserted, _ = self._upsert_post_connection(conn, job_id, post, now)
        return inserted

    @staticmethod
    def _upsert_post_connection(
        conn: sqlite3.Connection,
        job_id: str,
        post: PostRecord,
        now: str | None,
    ) -> tuple[bool, bool]:
        incoming_payload = post.to_dict()
        incoming_json = json.dumps(
            incoming_payload,
            ensure_ascii=False,
            sort_keys=True,
        )
        existing = conn.execute(
            "SELECT source_set, payload FROM posts WHERE job_id=? AND post_id=?",
            (job_id, post.post_id),
        ).fetchone()
        if existing is None:
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
                    incoming_json,
                    now,
                    now,
                ),
            )
            return True, False

        existing_payload = json.loads(existing["payload"])
        existing_hash = post_material_sha256(existing_payload)
        incoming_hash = post_material_sha256(incoming_payload)
        conflict = existing_hash != incoming_hash
        sources = set(json.loads(existing["source_set"]))
        sources.add(post.source)
        conn.execute(
            """UPDATE posts SET source_set=?, updated_at=?
            WHERE job_id=? AND post_id=?""",
            (json.dumps(sorted(sources)), now, job_id, post.post_id),
        )
        if conflict:
            conn.execute(
                """INSERT OR IGNORE INTO post_conflicts
                (job_id, post_id, canonical_material_sha256, observed_material_sha256,
                 observed_source, canonical_material, observed_material, detected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    post.post_id,
                    existing_hash,
                    incoming_hash,
                    post.source,
                    json.dumps(
                        post_material_payload(existing_payload),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    json.dumps(
                        post_material_payload(incoming_payload),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now,
                ),
            )
        return False, conflict

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

    def list_post_ids(self, job_id: str) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT post_id FROM posts WHERE job_id=? ORDER BY post_id",
                (job_id,),
            ).fetchall()
        return [str(row["post_id"]) for row in rows]

    def list_post_conflicts(self, job_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM post_conflicts WHERE job_id=?
                ORDER BY post_id, observed_source, observed_material_sha256""",
                (job_id,),
            ).fetchall()
        conflicts: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["canonical_material"] = json.loads(item["canonical_material"])
            item["observed_material"] = json.loads(item["observed_material"])
            conflicts.append(redact_value(item))
        return conflicts

    def count_post_conflicts(self, job_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM post_conflicts WHERE job_id=?",
                (job_id,),
            ).fetchone()
        return int(row[0])

    def post_source_counts(self, job_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for post in self.iter_posts(job_id):
            for source in post.get("sources", []):
                counts[str(source)] = counts.get(str(source), 0) + 1
        return dict(sorted(counts.items()))

    def list_events(self, job_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT event_id, occurred_at, event_type, details
                FROM events WHERE job_id=? ORDER BY event_id""",
                (job_id,),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item["details"])
            events.append(redact_value(item))
        return events

    def latest_evidence_at(self, job_id: str) -> str:
        candidates: list[str] = []
        queries = (
            ("jobs", "updated_at"),
            ("windows", "updated_at"),
            ("posts", "updated_at"),
            ("user_snapshots", "captured_at"),
            ("events", "occurred_at"),
            ("harvest_scopes", "updated_at"),
            ("harvest_pages", "committed_at"),
        )
        with self.connect() as conn:
            for table, column in queries:
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                if exists is None:
                    continue
                row = conn.execute(
                    f"SELECT MAX({column}) FROM {table} WHERE job_id=?",
                    (job_id,),
                ).fetchone()
                if row is not None and row[0]:
                    candidates.append(str(row[0]))
        if not candidates:
            raise KeyError(job_id)
        return max(candidates)

    def add_event(self, job_id: str, event_type: str, details: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO events(job_id, occurred_at, event_type, details) VALUES (?, ?, ?, ?)",
                (
                    job_id,
                    iso_utc(utc_now()),
                    event_type,
                    json.dumps(
                        redact_value(details),
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ),
                ),
            )
