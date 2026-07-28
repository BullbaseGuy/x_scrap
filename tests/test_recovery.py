from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fakes import FakeAdapter, post, user

from x_scrap.adapters.base import RateLimited, TransientUpstreamError, UpstreamChanged
from x_scrap.runtime.recovery import RecoveryBudget
from x_scrap.runtime.retry import RetryPolicy
from x_scrap.service import UserExportService
from x_scrap.storage.database import Database


class FlakyTimelineAdapter(FakeAdapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timeline_calls = 0

    def iter_user_tweet_pages(self, user_id, *, cursor=None, limit=-1):
        async def stream():
            self.timeline_calls += 1
            call = self.timeline_calls
            async for page in self._pages(
                self.timeline,
                source="user_tweets",
                operation="UserTweets",
                cursor=cursor,
                limit=limit,
            ):
                yield page
                if call == 1:
                    raise TransientUpstreamError("temporary connection reset 503")

        return stream()


class RateLimitedSearchAdapter(FakeAdapter):
    def __init__(self, *args, reset_at: datetime, **kwargs):
        super().__init__(*args, **kwargs)
        self.reset_at = reset_at
        self.search_calls = 0

    def iter_search_pages(self, query, *, cursor=None, limit=-1):
        async def stream():
            self.search_calls += 1
            if self.search_calls == 1:
                raise RateLimited("429 rate limit", reset_at=self.reset_at)
            async for page in super(RateLimitedSearchAdapter, self).iter_search_pages(
                query, cursor=cursor, limit=limit
            ):
                yield page

        return stream()


class AlwaysTransientSearchAdapter(FakeAdapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.search_calls = 0

    def iter_search_pages(self, query, *, cursor=None, limit=-1):
        async def stream():
            self.search_calls += 1
            raise TransientUpstreamError("temporary connection reset 503")
            yield  # pragma: no cover

        return stream()


class SchemaChangedSearchAdapter(FakeAdapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.search_calls = 0

    def iter_search_pages(self, query, *, cursor=None, limit=-1):
        async def stream():
            self.search_calls += 1
            raise UpstreamChanged("GraphQL operation missing 404")
            yield  # pragma: no cover

        return stream()


async def _recording_sleep(delays: list[float], delay: float) -> None:
    delays.append(delay)


def _service(tmp_path, adapter, *, delays, policy=None, clock=None):
    database = Database(tmp_path / "jobs.db")
    service = UserExportService(
        adapter,
        database,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        retry_policy=policy,
        sleep=lambda delay: _recording_sleep(delays, delay),
        clock=clock or (lambda: datetime(2026, 1, 1, tzinfo=UTC)),
        heartbeat_interval=999,
    )
    return database, service


def test_recovery_budget_separates_rate_limits_from_transient_root_cause_budget():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    policy = RetryPolicy(
        infrastructure_retry_limit=3,
        same_root_cause_limit=2,
        rate_limit_retry_limit=2,
        base_delay_seconds=1,
        rate_limit_safety_seconds=2,
    )
    budget = RecoveryBudget(policy)

    rate = budget.decide(
        RateLimited("429", reset_at=now + timedelta(seconds=30)), now=now
    )
    assert rate.retry is True
    assert rate.delay_seconds == 32
    assert budget.total_transient_failures == 0

    assert budget.decide(TransientUpstreamError("503 request 100"), now=now).retry is True
    assert budget.decide(TransientUpstreamError("503 request 200"), now=now).retry is True
    exhausted = budget.decide(TransientUpstreamError("503 request 300"), now=now)
    assert exhausted.retry is False
    assert exhausted.exhausted_reason == "SAME_ROOT_CAUSE_RETRY_BUDGET_EXHAUSTED"


@pytest.mark.asyncio
async def test_timeline_transient_failure_resumes_from_committed_cursor_automatically(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    values = [
        post(1, start + timedelta(hours=1)),
        post(2, start + timedelta(hours=2)),
    ]
    adapter = FlakyTimelineAdapter(
        timeline=values,
        searches={"from:alice": values},
        page_size=1,
        resolved_user=user(created=start, statuses_count=2),
    )
    delays: list[float] = []
    database, service = _service(tmp_path, adapter, delays=delays)

    result = await service.export_user(
        "alice",
        start=start,
        cutoff=start + timedelta(days=1),
        max_posts_per_window=100,
    )

    assert result["coverage_status"] == "COMPLETE_PUBLICLY_RETRIEVABLE"
    assert delays == [1]
    timeline_requests = [row for row in adapter.page_requests if row[0] == "user_tweets"]
    assert timeline_requests == [
        ("user_tweets", None, -1),
        ("user_tweets", "offset:1", -1),
    ]
    events = database.list_events(result["job_id"])
    assert [row["event_type"] for row in events].count("TRANSIENT_RETRY") == 1


@pytest.mark.asyncio
async def test_search_rate_limit_waits_until_reset_without_using_transient_budget(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    value = post(1, now + timedelta(hours=1))
    adapter = RateLimitedSearchAdapter(
        searches={"from:alice": [value]},
        reset_at=now + timedelta(seconds=30),
        resolved_user=user(created=now, statuses_count=0),
    )
    delays: list[float] = []
    policy = RetryPolicy(rate_limit_safety_seconds=2)
    database, service = _service(
        tmp_path,
        adapter,
        delays=delays,
        policy=policy,
        clock=lambda: now,
    )

    result = await service.export_user(
        "alice",
        start=now,
        cutoff=now + timedelta(days=1),
        max_posts_per_window=100,
    )

    assert result["coverage_status"] == "COMPLETE_PUBLICLY_RETRIEVABLE"
    assert adapter.search_calls == 2
    assert delays == [32]
    events = database.list_events(result["job_id"])
    waits = [row for row in events if row["event_type"] == "RATE_LIMIT_WAIT"]
    assert len(waits) == 1
    assert waits[0]["details"]["reset_at"] == "2026-01-01T00:00:30Z"
    assert waits[0]["details"]["delay_seconds"] == 32


@pytest.mark.asyncio
async def test_same_transient_root_cause_stops_after_budget_instead_of_looping(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    adapter = AlwaysTransientSearchAdapter(
        resolved_user=user(created=start, statuses_count=0)
    )
    delays: list[float] = []
    policy = RetryPolicy(
        infrastructure_retry_limit=5,
        same_root_cause_limit=2,
        base_delay_seconds=1,
    )
    database, service = _service(tmp_path, adapter, delays=delays, policy=policy)

    with pytest.raises(TransientUpstreamError):
        await service.export_user(
            "alice",
            start=start,
            cutoff=start + timedelta(days=1),
            max_posts_per_window=100,
        )

    assert adapter.search_calls == 3
    assert delays == [1, 2]
    job = database.list_jobs(1)[0]
    assert job["status"] == "FAILED"
    events = database.list_events(job["job_id"])
    exhausted = [row for row in events if row["event_type"] == "RECOVERY_EXHAUSTED"]
    assert len(exhausted) == 1
    assert (
        exhausted[0]["details"]["exhausted_reason"]
        == "SAME_ROOT_CAUSE_RETRY_BUDGET_EXHAUSTED"
    )


@pytest.mark.asyncio
async def test_schema_change_is_not_blindly_retried(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    adapter = SchemaChangedSearchAdapter(
        resolved_user=user(created=start, statuses_count=0)
    )
    delays: list[float] = []
    database, service = _service(tmp_path, adapter, delays=delays)

    with pytest.raises(UpstreamChanged):
        await service.export_user(
            "alice",
            start=start,
            cutoff=start + timedelta(days=1),
            max_posts_per_window=100,
        )

    assert adapter.search_calls == 1
    assert delays == []
    assert database.list_jobs(1)[0]["status"] == "UPSTREAM_SCHEMA_CHANGED"
