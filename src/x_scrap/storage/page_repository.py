from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from x_scrap.domain.models import PostRecord, iso_utc, utc_now
from x_scrap.domain.pages import CollectorPage
from x_scrap.storage.database import Database
from x_scrap.storage.raw_store import RawArtifact


class PageRepository:
    """Atomic SQLite state for page evidence, posts, and resume cursors."""

    def __init__(self, database: Database):
        self.database = database
        self.initialize()

    def initialize(self) -> None:
        with self.database.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS harvest_scopes (
                    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                    scope_key TEXT NOT NULL,
                    source TEXT NOT NULL,
                    state TEXT NOT NULL,
                    next_cursor TEXT,
                    next_page_index INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(job_id, scope_key)
                );
                CREATE INDEX IF NOT EXISTS idx_harvest_scopes_state
                    ON harvest_scopes(job_id, state, scope_key);

                CREATE TABLE IF NOT EXISTS harvest_pages (
                    job_id TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    page_index INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    request_cursor TEXT,
                    next_cursor TEXT,
                    payload_sha256 TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    artifact_size INTEGER NOT NULL,
                    item_count INTEGER NOT NULL,
                    accepted_count INTEGER NOT NULL,
                    oldest_post_at TEXT,
                    newest_post_at TEXT,
                    captured_at TEXT NOT NULL,
                    committed_at TEXT NOT NULL,
                    PRIMARY KEY(job_id, scope_key, page_index),
                    UNIQUE(job_id, scope_key, payload_sha256),
                    FOREIGN KEY(job_id, scope_key)
                        REFERENCES harvest_scopes(job_id, scope_key) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_harvest_pages_cursor
                    ON harvest_pages(job_id, scope_key, next_cursor);

                CREATE TABLE IF NOT EXISTS harvest_page_posts (
                    job_id TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    page_index INTEGER NOT NULL,
                    post_id TEXT NOT NULL,
                    PRIMARY KEY(job_id, scope_key, page_index, post_id),
                    FOREIGN KEY(job_id, scope_key, page_index)
                        REFERENCES harvest_pages(job_id, scope_key, page_index) ON DELETE CASCADE,
                    FOREIGN KEY(job_id, post_id)
                        REFERENCES posts(job_id, post_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_harvest_page_posts_post
                    ON harvest_page_posts(job_id, post_id);
                """
            )
            self._ensure_column(conn, "harvest_pages", "oldest_post_at", "TEXT")
            self._ensure_column(conn, "harvest_pages", "newest_post_at", "TEXT")

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection, table: str, column: str, declaration: str
    ) -> None:
        columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def ensure_scope(self, job_id: str, scope_key: str, source: str) -> dict[str, Any]:
        now = iso_utc(utc_now())
        with self.database.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO harvest_scopes
                (job_id, scope_key, source, state, updated_at)
                VALUES (?, ?, ?, 'PENDING', ?)""",
                (job_id, scope_key, source, now),
            )
            row = conn.execute(
                "SELECT * FROM harvest_scopes WHERE job_id=? AND scope_key=?",
                (job_id, scope_key),
            ).fetchone()
        if row is None:
            raise RuntimeError(f"failed to create harvest scope {scope_key}")
        if row["source"] != source:
            raise ValueError(f"scope {scope_key} is already bound to source {row['source']}")
        return dict(row)

    def get_scope(self, job_id: str, scope_key: str) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM harvest_scopes WHERE job_id=? AND scope_key=?",
                (job_id, scope_key),
            ).fetchone()
        return dict(row) if row else None

    def commit_page(
        self,
        job_id: str,
        scope_key: str,
        page: CollectorPage,
        artifact: RawArtifact,
        posts: list[PostRecord],
    ) -> bool:
        """Commit page metadata, normalized posts, links, and next cursor together."""

        now = iso_utc(utc_now())
        unique_posts = {post.post_id: post for post in posts}
        post_times = [post.created_at for post in unique_posts.values()]
        oldest_post_at = iso_utc(min(post_times)) if post_times else None
        newest_post_at = iso_utc(max(post_times)) if post_times else None
        with self.database.connect() as conn:
            scope = conn.execute(
                "SELECT * FROM harvest_scopes WHERE job_id=? AND scope_key=?",
                (job_id, scope_key),
            ).fetchone()
            if scope is None:
                raise KeyError(f"unknown harvest scope: {scope_key}")

            existing = conn.execute(
                """SELECT payload_sha256 FROM harvest_pages
                WHERE job_id=? AND scope_key=? AND page_index=?""",
                (job_id, scope_key, page.page_index),
            ).fetchone()
            if existing is not None:
                if existing["payload_sha256"] == artifact.sha256:
                    return False
                raise ValueError(
                    f"page index {page.page_index} for {scope_key} already has a different payload"
                )

            duplicate_payload = conn.execute(
                """SELECT page_index FROM harvest_pages
                WHERE job_id=? AND scope_key=? AND payload_sha256=? LIMIT 1""",
                (job_id, scope_key, artifact.sha256),
            ).fetchone()
            if duplicate_payload is not None:
                raise ValueError(
                    f"payload for {scope_key} duplicates page {duplicate_payload['page_index']}"
                )

            expected_index = int(scope["next_page_index"])
            if page.page_index != expected_index:
                raise ValueError(
                    f"page index mismatch for {scope_key}: expected {expected_index}, got {page.page_index}"
                )
            if page.request_cursor != scope["next_cursor"]:
                raise ValueError(f"request cursor mismatch for {scope_key}")

            if page.next_cursor is not None:
                repeated = conn.execute(
                    """SELECT page_index FROM harvest_pages
                    WHERE job_id=? AND scope_key=? AND request_cursor=? AND page_index < ?
                    LIMIT 1""",
                    (job_id, scope_key, page.next_cursor, page.page_index),
                ).fetchone()
                if repeated is not None:
                    raise ValueError(
                        f"pagination cursor for {scope_key} repeated page {repeated['page_index']}"
                    )

            conn.execute(
                """INSERT INTO harvest_pages
                (job_id, scope_key, page_index, source, operation, request_cursor, next_cursor,
                 payload_sha256, artifact_path, artifact_size, item_count, accepted_count,
                 oldest_post_at, newest_post_at, captured_at, committed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    scope_key,
                    page.page_index,
                    page.source,
                    page.operation,
                    page.request_cursor,
                    page.next_cursor,
                    artifact.sha256,
                    str(Path(artifact.path)),
                    artifact.size,
                    len(page.items),
                    len(unique_posts),
                    oldest_post_at,
                    newest_post_at,
                    iso_utc(page.captured_at),
                    now,
                ),
            )
            for post in unique_posts.values():
                self._upsert_post(conn, job_id, post, now)
                conn.execute(
                    """INSERT INTO harvest_page_posts(job_id, scope_key, page_index, post_id)
                    VALUES (?, ?, ?, ?)""",
                    (job_id, scope_key, page.page_index, post.post_id),
                )
            next_state = "EXHAUSTED" if page.next_cursor is None else "RUNNING"
            conn.execute(
                """UPDATE harvest_scopes
                SET state=?, next_cursor=?, next_page_index=?, last_error=NULL, updated_at=?
                WHERE job_id=? AND scope_key=?""",
                (next_state, page.next_cursor, page.page_index + 1, now, job_id, scope_key),
            )
        return True

    def complete_scope(self, job_id: str, scope_key: str) -> None:
        self._set_scope_state(job_id, scope_key, "COMPLETE", None)

    def limit_scope(self, job_id: str, scope_key: str, reason: str) -> None:
        self._set_scope_state(job_id, scope_key, "LIMIT_REACHED", reason)

    def fail_scope(self, job_id: str, scope_key: str, error: str) -> None:
        self._set_scope_state(job_id, scope_key, "FAILED", error)

    def _set_scope_state(
        self, job_id: str, scope_key: str, state: str, detail: str | None
    ) -> None:
        with self.database.connect() as conn:
            result = conn.execute(
                """UPDATE harvest_scopes
                SET state=?, last_error=?, updated_at=?
                WHERE job_id=? AND scope_key=?""",
                (state, detail, iso_utc(utc_now()), job_id, scope_key),
            )
            if result.rowcount != 1:
                raise KeyError(f"unknown harvest scope: {scope_key}")

    def list_pages(self, job_id: str, scope_key: str | None = None) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            if scope_key is None:
                rows = conn.execute(
                    """SELECT * FROM harvest_pages WHERE job_id=?
                    ORDER BY scope_key, page_index""",
                    (job_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM harvest_pages WHERE job_id=? AND scope_key=?
                    ORDER BY page_index""",
                    (job_id, scope_key),
                ).fetchall()
        return [dict(row) for row in rows]

    def page_post_ids(self, job_id: str, scope_key: str, page_index: int) -> list[str]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT post_id FROM harvest_page_posts
                WHERE job_id=? AND scope_key=? AND page_index=? ORDER BY post_id""",
                (job_id, scope_key, page_index),
            ).fetchall()
        return [str(row["post_id"]) for row in rows]

    def scope_stats(self, job_id: str, scope_key: str) -> dict[str, Any]:
        with self.database.connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS page_count,
                          COALESCE(SUM(item_count), 0) AS item_count,
                          COALESCE((
                              SELECT COUNT(DISTINCT post_id) FROM harvest_page_posts
                              WHERE job_id=? AND scope_key=?
                          ), 0) AS accepted_count,
                          MIN(oldest_post_at) AS oldest_post_at,
                          MAX(newest_post_at) AS newest_post_at
                   FROM harvest_pages WHERE job_id=? AND scope_key=?""",
                (job_id, scope_key, job_id, scope_key),
            ).fetchone()
        return dict(row)

    def count_pages(self, job_id: str) -> int:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM harvest_pages WHERE job_id=?", (job_id,)
            ).fetchone()
        return int(row[0])

    @staticmethod
    def _upsert_post(
        conn: sqlite3.Connection, job_id: str, post: PostRecord, now: str | None
    ) -> None:
        payload = post.to_json()
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
            return
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
