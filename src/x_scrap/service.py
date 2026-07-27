from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
from x_scrap.domain.pages import CollectorPage
from x_scrap.export.writer import write_export
from x_scrap.harvest.window_planner import build_search_query, make_windows, split_window
from x_scrap.runtime.heartbeat import Heartbeat
from x_scrap.runtime.retry import RetryPolicy
from x_scrap.storage.database import Database
from x_scrap.storage.page_repository import PageRepository
from x_scrap.storage.raw_store import RawStore

EARLIEST_X = datetime(2006, 3, 21, tzinfo=UTC)
_SAFE_SCOPE_RE = re.compile(r"[^A-Za-z0-9._-]+")


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
        self.pages = PageRepository(database)
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
        if max_posts_per_window < 1:
            raise ValueError("max_posts_per_window must be positive")
        if timeline_limit == 0 or timeline_limit < -1:
            raise ValueError("timeline_limit must be -1 or positive")

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
                "pages": self.pages.count_pages(job_id),
                "windows_complete": sum(
                    row["status"] == WindowStatus.COMPLETE.value for row in windows
                ),
                "windows_pending": sum(
                    row["status"] == WindowStatus.PENDING.value for row in windows
                ),
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
                    await self._collect_timeline(
                        job_id, user.user_id, include_retweets, timeline_limit
                    )
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
                    "schema_version": "1.1.0",
                    "job_id": job_id,
                    "username": username,
                    "user_id": user.user_id,
                    "start_at": iso_utc(start),
                    "cutoff_at": iso_utc(cutoff),
                    "post_count": self.db.count_posts(job_id),
                    "page_count": self.pages.count_pages(job_id),
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
            (
                "user_tweets",
                "timeline:user_tweets",
                self.adapter.iter_user_tweet_pages,
            ),
            (
                "user_tweets_and_replies",
                "timeline:user_tweets_and_replies",
                self.adapter.iter_user_tweet_and_reply_pages,
            ),
        ]
        for source, scope_key, factory in sources:
            scope = self.pages.ensure_scope(job_id, scope_key, source)
            if scope["state"] == "COMPLETE":
                continue
            if scope["state"] == "EXHAUSTED":
                self.pages.complete_scope(job_id, scope_key)
                continue

            stats = self.pages.scope_stats(job_id, scope_key)
            remaining = -1 if limit < 0 else max(0, limit - int(stats["item_count"]))
            if remaining == 0:
                self.pages.limit_scope(job_id, scope_key, "CONFIGURED_TIMELINE_LIMIT")
            else:
                try:
                    stream = factory(
                        user_id,
                        cursor=scope["next_cursor"],
                        limit=remaining,
                    )
                    await self._consume_page_stream(
                        job_id,
                        scope_key,
                        source,
                        stream,
                        include_retweets=include_retweets,
                    )
                    self._finish_scope_after_stream(
                        job_id,
                        scope_key,
                        allow_limit=limit > 0,
                        limit_reason="CONFIGURED_TIMELINE_LIMIT",
                    )
                except Exception as exc:
                    self.pages.fail_scope(job_id, scope_key, type(exc).__name__)
                    raise

            final_stats = self.pages.scope_stats(job_id, scope_key)
            final_scope = self.pages.get_scope(job_id, scope_key)
            self.db.add_event(
                job_id,
                "TIMELINE_SOURCE_COMPLETE",
                {
                    "source": source,
                    "state": final_scope["state"] if final_scope else "UNKNOWN",
                    "pages": final_stats["page_count"],
                    "count": final_stats["accepted_count"],
                },
            )

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
            start = parse_datetime(row["start_at"])
            end = parse_datetime(row["end_at"])
            if start is None or end is None:
                raise ValueError(f"window {row['window_id']} has invalid timestamps")
            window = TimeWindow(start, end, int(row["depth"]))
            window_id = row["window_id"]
            attempts = int(row["attempts"]) + 1
            self.db.update_window(window_id, status=WindowStatus.RUNNING, attempts=attempts)
            query = build_search_query(username, window, include_retweets=include_retweets)
            try:
                stats = await self._consume_search_window(
                    job_id,
                    window_id,
                    window,
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

            exhausted = bool(stats["exhausted"])
            if not exhausted and window.duration_seconds > min_window_seconds:
                left, right = split_window(window)
                self.db.update_window(
                    window_id,
                    status=WindowStatus.SPLIT,
                    post_count=stats["accepted_count"],
                    oldest_post_at=stats["oldest_post_at"],
                    newest_post_at=stats["newest_post_at"],
                    terminal_reason="CURSOR_REMAINS_SPLIT",
                )
                self.db.add_windows(job_id, "search", [left, right])
            elif not exhausted:
                self.db.update_window(
                    window_id,
                    status=WindowStatus.PARTIAL_LIMIT_REACHED,
                    post_count=stats["accepted_count"],
                    oldest_post_at=stats["oldest_post_at"],
                    newest_post_at=stats["newest_post_at"],
                    terminal_reason="MINIMUM_WINDOW_CURSOR_REMAINS",
                )
            else:
                self.db.update_window(
                    window_id,
                    status=WindowStatus.COMPLETE,
                    post_count=stats["accepted_count"],
                    oldest_post_at=stats["oldest_post_at"],
                    newest_post_at=stats["newest_post_at"],
                    terminal_reason="SOURCE_EXHAUSTED",
                )

    async def _consume_search_window(
        self,
        job_id: str,
        window_id: str,
        window: TimeWindow,
        query: str,
        include_retweets: bool,
        limit: int,
    ) -> dict[str, Any]:
        scope_key = f"window:{window_id}"
        scope = self.pages.ensure_scope(job_id, scope_key, "search")
        if scope["state"] == "EXHAUSTED":
            self.pages.complete_scope(job_id, scope_key)
            return self._search_scope_stats(job_id, scope_key, exhausted=True)
        if scope["state"] == "COMPLETE":
            return self._search_scope_stats(job_id, scope_key, exhausted=True)
        if scope["state"] == "LIMIT_REACHED":
            return self._search_scope_stats(job_id, scope_key, exhausted=False)

        current_stats = self.pages.scope_stats(job_id, scope_key)
        remaining = max(0, limit - int(current_stats["item_count"]))
        if remaining == 0:
            self.pages.limit_scope(job_id, scope_key, "WINDOW_ITEM_BUDGET_REACHED")
            return self._search_scope_stats(job_id, scope_key, exhausted=False)

        try:
            stream = self.adapter.iter_search_pages(
                query,
                cursor=scope["next_cursor"],
                limit=remaining,
            )
            await self._consume_page_stream(
                job_id,
                scope_key,
                "search",
                stream,
                include_retweets=include_retweets,
                window=window,
            )
            exhausted = self._finish_scope_after_stream(
                job_id,
                scope_key,
                allow_limit=True,
                limit_reason="WINDOW_ITEM_BUDGET_REACHED",
            )
        except Exception as exc:
            self.pages.fail_scope(job_id, scope_key, type(exc).__name__)
            raise
        return self._search_scope_stats(job_id, scope_key, exhausted=exhausted)

    async def _consume_page_stream(
        self,
        job_id: str,
        scope_key: str,
        source: str,
        stream: AsyncIterator[CollectorPage],
        *,
        include_retweets: bool,
        window: TimeWindow | None = None,
    ) -> None:
        scope = self.pages.get_scope(job_id, scope_key)
        if scope is None:
            raise KeyError(f"unknown harvest scope: {scope_key}")
        page_index = int(scope["next_page_index"])

        async for upstream_page in stream:
            if upstream_page.source != source:
                raise UpstreamChanged(
                    f"adapter returned source {upstream_page.source} for expected {source}"
                )
            page = replace(upstream_page, page_index=page_index)
            records: dict[str, PostRecord] = {}
            for item in page.items:
                post = PostRecord.from_object(item, source=source)
                if post.is_retweet and not include_retweets:
                    continue
                if window is not None and not (window.start <= post.created_at < window.end):
                    continue
                records[post.post_id] = post

            safe_scope = _SAFE_SCOPE_RE.sub("_", scope_key).strip("_") or "scope"
            artifact = self.raw_store.write_content_addressed_json(
                Path(job_id) / "pages" / safe_scope,
                page.artifact_payload(),
                prefix=f"page-{page_index:06d}",
            )
            self.pages.commit_page(job_id, scope_key, page, artifact, list(records.values()))
            self.db.add_event(
                job_id,
                "PAGE_COMMITTED",
                {
                    "scope_key": scope_key,
                    "page_index": page_index,
                    "item_count": len(page.items),
                    "accepted_count": len(records),
                    "payload_sha256": artifact.sha256,
                },
            )
            page_index += 1

    def _finish_scope_after_stream(
        self,
        job_id: str,
        scope_key: str,
        *,
        allow_limit: bool,
        limit_reason: str,
    ) -> bool:
        scope = self.pages.get_scope(job_id, scope_key)
        if scope is None:
            raise KeyError(f"unknown harvest scope: {scope_key}")
        stats = self.pages.scope_stats(job_id, scope_key)
        if scope["state"] == "EXHAUSTED" or (
            int(stats["page_count"]) == 0 and scope["next_cursor"] is None
        ):
            self.pages.complete_scope(job_id, scope_key)
            return True
        if allow_limit:
            self.pages.limit_scope(job_id, scope_key, limit_reason)
            return False
        raise UpstreamChanged(f"{scope_key} stopped while a pagination cursor remained")

    def _search_scope_stats(
        self, job_id: str, scope_key: str, *, exhausted: bool
    ) -> dict[str, Any]:
        stats = self.pages.scope_stats(job_id, scope_key)
        return {**stats, "exhausted": exhausted}
