from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from x_scrap.adapters.base import (
    AuthRequired,
    CollectorAdapter,
    RateLimited,
    TransientUpstreamError,
    UpstreamChanged,
)
from x_scrap.audit.coverage import audit_coverage
from x_scrap.domain.models import (
    CoverageStatus,
    JobStatus,
    PostRecord,
    TimeWindow,
    UserSnapshot,
    WindowStatus,
    iso_utc,
    parse_datetime,
    utc_now,
)
from x_scrap.export.writer import write_export
from x_scrap.harvest.window_planner import build_search_query, make_windows, split_window
from x_scrap.runtime.heartbeat import Heartbeat
from x_scrap.runtime.retry import RetryPolicy
from x_scrap.storage.database import Database
from x_scrap.storage.raw_store import RawStore

UTC = timezone.utc
EARLIEST_X = datetime(2006, 3, 21, tzinfo=UTC)


class UserExportService:
    def __init__(
        self,
        adapter: CollectorAdapter,
        database: Database,
        *,
        exports_root: Path,
        raw_root: Path,
        retry_policy: RetryPolicy | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
        heartbeat_interval: float = 45.0,
    ):
        self.adapter = adapter
        self.db = database
        self.exports_root = exports_root
        self.raw_store = RawStore(raw_root)
        self.retry_policy = retry_policy or RetryPolicy()
        self.sleep = sleep
        self.heartbeat_interval = heartbeat_interval

    async def export_user(
        self,
        username: str,
        *,
        start: datetime | None = None,
        cutoff: datetime | None = None,
        resume: bool = True,
        include_retweets: bool = False,
        initial_window_days: int = 30,
        min_window_seconds: int = 3600,
        max_posts_per_window: int = 5000,
        timeline_limit: int = -1,
    ) -> dict[str, Any]:
        username = username.lstrip("@")
        cutoff = cutoff or utc_now()
        resumable = self.db.find_resumable_job(username) if resume else None
        if resumable:
            job_id = resumable["job_id"]
            output_dir = Path(resumable["output_dir"])
            cutoff = parse_datetime(resumable["cutoff_at"]) or cutoff
            if start is None:
                start = parse_datetime(resumable["start_at"])
        else:
            provisional = self.exports_root / username / "pending"
            job_id = self.db.create_job(
                username=username,
                cutoff_at=cutoff,
                scope="authored+retweets" if include_retweets else "authored",
                output_dir=provisional,
                start_at=start,
            )
            output_dir = self.exports_root / username / job_id
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE jobs SET output_dir=? WHERE job_id=?", (str(output_dir), job_id)
                )
        self.db.update_job(job_id, status=JobStatus.RUNNING, error_code=None, error_message=None)
        self.db.add_event(job_id, "JOB_STARTED", {"username": username, "resume": bool(resumable)})

        def snapshot() -> dict[str, object]:
            windows = self.db.all_windows(job_id)
            return {
                "job_id": job_id,
                "status": self.db.get_job(job_id)["status"],
                "posts": self.db.count_posts(job_id),
                "windows_complete": sum(row["status"] == WindowStatus.COMPLETE.value for row in windows),
                "windows_pending": sum(row["status"] == WindowStatus.PENDING.value for row in windows),
                "updated_at": iso_utc(utc_now()),
            }

        try:
            async with Heartbeat(snapshot, interval_seconds=self.heartbeat_interval):
                profile = self.db.get_user_snapshot(job_id)
                if profile is None:
                    upstream_user = await self.adapter.resolve_user(username)
                    user = UserSnapshot.from_object(upstream_user)
                    profile = user.to_dict()
                    self.db.save_user_snapshot(job_id, profile)
                    start = start or user.created_at or EARLIEST_X
                    start = max(start, EARLIEST_X)
                    self.db.update_job(job_id, user_id=user.user_id, start_at=iso_utc(start))
                else:
                    user = UserSnapshot.from_object(profile)
                    start = start or user.created_at or EARLIEST_X
                    start = max(start, EARLIEST_X)

                if not self.db.all_windows(job_id):
                    await self._collect_timeline(job_id, user.user_id, include_retweets, timeline_limit)
                    self.db.add_windows(
                        job_id,
                        "search",
                        make_windows(start, cutoff, days=initial_window_days),
                    )

                await self._collect_search_windows(
                    job_id,
                    username,
                    include_retweets=include_retweets,
                    min_window_seconds=min_window_seconds,
                    max_posts_per_window=max_posts_per_window,
                )

                windows = self.db.all_windows(job_id)
                coverage = audit_coverage(windows, start, cutoff)
                coverage_status = coverage["status"]
                final_status = (
                    JobStatus.COMPLETED
                    if coverage_status == CoverageStatus.COMPLETE_PUBLICLY_RETRIEVABLE.value
                    else JobStatus.PARTIAL
                )
                self.db.update_job(
                    job_id,
                    status=final_status,
                    coverage_status=coverage_status,
                )
                manifest = {
                    "schema_version": "1.0.0",
                    "job_id": job_id,
                    "username": username,
                    "user_id": user.user_id,
                    "start_at": iso_utc(start),
                    "cutoff_at": iso_utc(cutoff),
                    "post_count": self.db.count_posts(job_id),
                    "coverage_status": coverage_status,
                    "completed_at": iso_utc(utc_now()),
                    "collector": "x_scrap",
                    "adapter": type(self.adapter).__name__,
                }
                write_export(
                    output_dir,
                    manifest=manifest,
                    profile=profile,
                    coverage=coverage,
                    posts=self.db.iter_posts(job_id),
                )
                self.db.add_event(job_id, "JOB_FINISHED", manifest)
                return {**manifest, "output_dir": str(output_dir)}
        except AuthRequired as exc:
            self.db.update_job(
                job_id,
                status=JobStatus.HUMAN_REQUIRED,
                coverage_status=CoverageStatus.AUTH_REQUIRED.value,
                error_code="AUTH_REQUIRED",
                error_message=str(exc),
            )
            raise
        except UpstreamChanged as exc:
            self.db.update_job(
                job_id,
                status=JobStatus.UPSTREAM_SCHEMA_CHANGED,
                coverage_status=CoverageStatus.UPSTREAM_SCHEMA_CHANGED.value,
                error_code="UPSTREAM_SCHEMA_CHANGED",
                error_message=str(exc),
            )
            raise
        except Exception as exc:
            self.db.update_job(
                job_id,
                status=JobStatus.FAILED,
                error_code=type(exc).__name__,
                error_message=str(exc),
            )
            raise

    async def _collect_timeline(
        self, job_id: str, user_id: str, include_retweets: bool, limit: int
    ) -> None:
        sources = [
            ("user_tweets", self.adapter.iter_user_tweets(user_id, limit=limit)),
            (
                "user_tweets_and_replies",
                self.adapter.iter_user_tweets_and_replies(user_id, limit=limit),
            ),
        ]
        for source, stream in sources:
            count = await self._consume_stream(job_id, source, stream, include_retweets)
            self.db.add_event(job_id, "TIMELINE_SOURCE_COMPLETE", {"source": source, "count": count})

    async def _collect_search_windows(
        self,
        job_id: str,
        username: str,
        *,
        include_retweets: bool,
        min_window_seconds: int,
        max_posts_per_window: int,
    ) -> None:
        while True:
            pending = self.db.pending_windows(job_id)
            if not pending:
                return
            row = pending[0]
            window = TimeWindow(
                parse_datetime(row["start_at"]),
                parse_datetime(row["end_at"]),
                int(row["depth"]),
            )
            window_id = row["window_id"]
            attempts = int(row["attempts"]) + 1
            self.db.update_window(window_id, status=WindowStatus.RUNNING, attempts=attempts)
            query = build_search_query(username, window, include_retweets=include_retweets)
            try:
                stats = await self._consume_search_window(
                    job_id,
                    window_id,
                    query,
                    include_retweets,
                    max_posts_per_window,
                )
            except (RateLimited, TransientUpstreamError) as exc:
                if attempts > self.retry_policy.infrastructure_retry_limit:
                    self.db.update_window(
                        window_id,
                        status=WindowStatus.FAILED,
                        terminal_reason=type(exc).__name__,
                    )
                    raise
                self.db.update_job(job_id, status=JobStatus.WAITING_RATE_LIMIT)
                self.db.update_window(window_id, status=WindowStatus.PENDING)
                delay = self.retry_policy.delay_for_attempt(attempts)
                self.db.add_event(
                    job_id,
                    "RECOVERABLE_ERROR",
                    {"window_id": window_id, "error": type(exc).__name__, "delay": delay},
                )
                await self.sleep(delay)
                self.db.update_job(job_id, status=JobStatus.RUNNING)
                continue

            saturated = stats["seen"] >= max_posts_per_window
            if saturated and window.duration_seconds > min_window_seconds:
                left, right = split_window(window)
                self.db.update_window(
                    window_id,
                    status=WindowStatus.SPLIT,
                    post_count=stats["seen"],
                    oldest_post_at=stats["oldest"],
                    newest_post_at=stats["newest"],
                    terminal_reason="LIMIT_REACHED_SPLIT",
                )
                self.db.add_windows(job_id, "search", [left, right])
            elif saturated:
                self.db.update_window(
                    window_id,
                    status=WindowStatus.PARTIAL_LIMIT_REACHED,
                    post_count=stats["seen"],
                    oldest_post_at=stats["oldest"],
                    newest_post_at=stats["newest"],
                    terminal_reason="MINIMUM_WINDOW_STILL_SATURATED",
                )
            else:
                self.db.update_window(
                    window_id,
                    status=WindowStatus.COMPLETE,
                    post_count=stats["seen"],
                    oldest_post_at=stats["oldest"],
                    newest_post_at=stats["newest"],
                    terminal_reason="SOURCE_EXHAUSTED",
                )

    async def _consume_search_window(
        self,
        job_id: str,
        window_id: str,
        query: str,
        include_retweets: bool,
        limit: int,
    ) -> dict[str, Any]:
        seen = 0
        oldest: datetime | None = None
        newest: datetime | None = None
        async for item in self.adapter.iter_search(query, limit=limit):
            post = PostRecord.from_object(item, source="search")
            if post.is_retweet and not include_retweets:
                continue
            self.db.upsert_post(job_id, post)
            raw_rel = Path(job_id) / "search" / window_id.replace(":", "_") / f"{post.post_id}.json.gz"
            self.raw_store.write_json(raw_rel, post.raw)
            seen += 1
            oldest = min(oldest, post.created_at) if oldest else post.created_at
            newest = max(newest, post.created_at) if newest else post.created_at
        return {"seen": seen, "oldest": iso_utc(oldest), "newest": iso_utc(newest)}

    async def _consume_stream(
        self,
        job_id: str,
        source: str,
        stream: AsyncIterator[Any],
        include_retweets: bool,
    ) -> int:
        count = 0
        async for item in stream:
            post = PostRecord.from_object(item, source=source)
            if post.is_retweet and not include_retweets:
                continue
            self.db.upsert_post(job_id, post)
            raw_rel = Path(job_id) / source / f"{post.post_id}.json.gz"
            self.raw_store.write_json(raw_rel, post.raw)
            count += 1
        return count
