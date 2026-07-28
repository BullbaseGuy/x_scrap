from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fakes import FakeAdapter, post, user

from x_scrap.adapters.base import AuthRequired, TargetUnavailable, UpstreamChanged
from x_scrap.domain.models import PostRecord, TimeWindow, UserSnapshot
from x_scrap.domain.pages import CollectorPage
from x_scrap.service import UserExportService
from x_scrap.storage.database import Database


@pytest.mark.asyncio
async def test_export_is_idempotent_and_writes_auditable_outputs(tmp_path):
    created = datetime(2024, 1, 1, tzinfo=UTC)
    timeline_post = post(1, created + timedelta(hours=1))
    search_post = post(2, created + timedelta(days=1))
    adapter = FakeAdapter(
        timeline=[timeline_post],
        replies=[timeline_post],
        searches={"from:alice": [timeline_post, search_post]},
    )
    db = Database(tmp_path / "jobs.db")
    service = UserExportService(
        adapter,
        db,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )
    result = await service.export_user(
        "alice",
        start=created,
        cutoff=created + timedelta(days=2),
        initial_window_days=30,
        max_posts_per_window=100,
    )
    assert result["post_count"] == 2
    assert result["page_count"] == 3
    assert result["coverage_status"] == "COMPLETE_PUBLICLY_RETRIEVABLE"
    output = tmp_path / "exports" / "alice" / result["job_id"]
    assert (output / "tweets.jsonl").is_file()
    assert (output / "coverage.json").is_file()
    assert db.count_posts(result["job_id"]) == 2
    assert len(list((tmp_path / "raw" / result["job_id"] / "pages").rglob("*.json.gz"))) == 3


@pytest.mark.asyncio
async def test_saturated_window_is_split_until_source_exhausts(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    many = [post(i, start + timedelta(minutes=i)) for i in range(1, 5)]
    adapter = FakeAdapter(searches={"from:alice": many})
    db = Database(tmp_path / "jobs.db")
    service = UserExportService(
        adapter,
        db,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )
    result = await service.export_user(
        "alice",
        start=start,
        cutoff=start + timedelta(hours=2),
        initial_window_days=30,
        min_window_seconds=7200,
        max_posts_per_window=3,
    )
    assert result["coverage_status"] == "PARTIAL_UNRESOLVED_WINDOWS"
    windows = db.all_windows(result["job_id"])
    assert any(row["status"] == "PARTIAL_LIMIT_REACHED" for row in windows)


@pytest.mark.asyncio
async def test_resume_reuses_saved_profile_completed_windows_and_pages(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    adapter = FakeAdapter(searches={"from:alice": [post(10, start + timedelta(hours=1))]})
    db = Database(tmp_path / "jobs.db")
    service = UserExportService(
        adapter,
        db,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )
    first = await service.export_user(
        "alice",
        start=start,
        cutoff=start + timedelta(days=1),
        max_posts_per_window=100,
    )
    request_count = len(adapter.page_requests)
    db.update_job(first["job_id"], status="PARTIAL")
    second = await service.export_user("alice", resume=True)
    assert second["job_id"] == first["job_id"]
    assert second["post_count"] == 1
    assert second["page_count"] == first["page_count"]
    assert len(adapter.page_requests) == request_count


@pytest.mark.asyncio
async def test_resume_continues_from_the_next_committed_page_cursor(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    cutoff = start + timedelta(days=1)
    values = [post(i, start + timedelta(hours=i)) for i in range(1, 4)]
    adapter = FakeAdapter(searches={"from:alice": values}, page_size=1)
    db = Database(tmp_path / "jobs.db")
    service = UserExportService(
        adapter,
        db,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )
    job_id = db.create_job(
        username="alice",
        cutoff_at=cutoff,
        scope="authored",
        output_dir=tmp_path / "exports" / "alice" / "resume",
        start_at=start,
    )
    db.add_windows(job_id, "search", [TimeWindow(start, cutoff)])
    window_id = db.all_windows(job_id)[0]["window_id"]
    scope_key = f"window:{window_id}"
    service.pages.ensure_scope(job_id, scope_key, "search")

    first_page = CollectorPage(
        source="search",
        operation="SearchTimeline",
        request_cursor=None,
        next_cursor="offset:1",
        items=(values[0],),
        raw_payload={"tweets": [values[0]], "next_cursor": "offset:1"},
        page_index=0,
    )
    artifact = service.raw_store.write_content_addressed_json(
        Path(job_id) / "pages" / "seed",
        first_page.artifact_payload(),
        prefix="page-000000",
    )
    service.pages.commit_page(
        job_id,
        scope_key,
        first_page,
        artifact,
        [PostRecord.from_object(values[0], source="search")],
    )

    result = await service.export_user("alice", resume=True, max_posts_per_window=100)

    search_requests = [request for request in adapter.page_requests if request[0] == "search"]
    assert search_requests[0][1] == "offset:1"
    assert result["post_count"] == 3
    assert result["page_count"] == 3
    assert service.pages.page_post_ids(job_id, scope_key, 0) == ["1"]
    assert service.pages.get_scope(job_id, scope_key)["state"] == "COMPLETE"


@pytest.mark.asyncio
async def test_terminal_page_commit_resumes_without_restarting_the_source(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    cutoff = start + timedelta(days=1)
    value = post(1, start + timedelta(hours=1))
    adapter = FakeAdapter(searches={"from:alice": [value]}, page_size=1)
    db = Database(tmp_path / "jobs.db")
    service = UserExportService(
        adapter,
        db,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )
    job_id = db.create_job(
        username="alice",
        cutoff_at=cutoff,
        scope="authored",
        output_dir=tmp_path / "exports" / "alice" / "terminal-resume",
        start_at=start,
    )
    db.add_windows(job_id, "search", [TimeWindow(start, cutoff)])
    window_id = db.all_windows(job_id)[0]["window_id"]
    scope_key = f"window:{window_id}"
    service.pages.ensure_scope(job_id, scope_key, "search")
    terminal_page = CollectorPage(
        source="search",
        operation="SearchTimeline",
        request_cursor=None,
        next_cursor=None,
        items=(value,),
        raw_payload={"tweets": [value]},
        page_index=0,
    )
    artifact = service.raw_store.write_content_addressed_json(
        Path(job_id) / "pages" / "terminal-seed",
        terminal_page.artifact_payload(),
        prefix="page-000000",
    )
    service.pages.commit_page(
        job_id,
        scope_key,
        terminal_page,
        artifact,
        [PostRecord.from_object(value, source="search")],
    )
    assert service.pages.get_scope(job_id, scope_key)["state"] == "EXHAUSTED"

    result = await service.export_user("alice", resume=True, max_posts_per_window=100)

    assert not [request for request in adapter.page_requests if request[0] == "search"]
    assert result["coverage_status"] == "COMPLETE_PUBLICLY_RETRIEVABLE"
    assert result["post_count"] == 1
    assert service.pages.get_scope(job_id, scope_key)["state"] == "COMPLETE"


@pytest.mark.asyncio
async def test_recent_timelines_filter_author_and_fixed_range_and_preserve_relations(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    cutoff = start + timedelta(days=1)
    original = post(1, start + timedelta(hours=1))
    foreign = post(2, start + timedelta(hours=2), username="bob", user_id=8)
    before_start = post(3, start - timedelta(seconds=1))
    at_cutoff = post(4, cutoff)
    reply = post(
        5,
        start + timedelta(hours=3),
        inReplyToTweetId=1,
        inReplyToTweetIdStr="1",
    )
    quote = post(
        6,
        start + timedelta(hours=4),
        quotedTweet={"id": 99},
        isQuoteStatus=True,
        rawContent="long-form " + "x" * 400,
        media={"photos": [{"url": "https://pbs.twimg.com/media/example"}]},
    )
    native_repost = post(
        7,
        start + timedelta(hours=5),
        retweetedTweet={"id": 88},
    )
    adapter = FakeAdapter(
        timeline=[original, foreign, before_start, native_repost],
        replies=[original, reply, quote, at_cutoff],
        searches={"from:alice": []},
        resolved_user=user(statuses_count=7),
    )
    db = Database(tmp_path / "jobs.db")
    service = UserExportService(
        adapter,
        db,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )

    result = await service.export_user("Alice", start=start, cutoff=cutoff)
    records = {row["post_id"]: row for row in db.iter_posts(result["job_id"])}

    assert set(records) == {"1", "5", "6"}
    assert records["1"]["sources"] == ["user_tweets", "user_tweets_and_replies"]
    assert records["5"]["is_reply"] is True
    assert records["5"]["in_reply_to_post_id"] == "1"
    assert records["6"]["is_quote"] is True
    assert records["6"]["quoted_post_id"] == "99"
    assert records["6"]["text"].startswith("long-form ")
    assert records["6"]["media"]["photos"][0]["url"].startswith("https://pbs.twimg.com/")
    assert result["coverage_status"] == "COMPLETE_PUBLICLY_RETRIEVABLE"


@pytest.mark.asyncio
async def test_native_repost_policy_is_explicit_and_frozen_on_resume(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    cutoff = start + timedelta(days=1)
    native_repost = post(
        7,
        start + timedelta(hours=1),
        retweetedTweet={"id": 88},
    )
    adapter = FakeAdapter(
        timeline=[native_repost],
        searches={"from:alice": []},
        resolved_user=user(statuses_count=1),
    )
    db = Database(tmp_path / "jobs.db")
    service = UserExportService(
        adapter,
        db,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )

    result = await service.export_user(
        "alice",
        start=start,
        cutoff=cutoff,
        include_retweets=True,
    )
    stored = list(db.iter_posts(result["job_id"]))
    assert len(stored) == 1
    assert stored[0]["is_retweet"] is True
    assert stored[0]["reposted_post_id"] == "88"

    other_db = Database(tmp_path / "other-jobs.db")
    other_service = UserExportService(
        FakeAdapter(resolved_user=user(statuses_count=0)),
        other_db,
        exports_root=tmp_path / "other-exports",
        raw_root=tmp_path / "other-raw",
        heartbeat_interval=999,
    )
    other_db.create_job(
        username="alice",
        cutoff_at=cutoff,
        scope="authored",
        output_dir=tmp_path / "other-exports" / "alice" / "resume",
        start_at=start,
    )
    with pytest.raises(ValueError, match="native repost policy"):
        await other_service.export_user("alice", include_retweets=True)


@pytest.mark.asyncio
async def test_recent_timeline_scopes_resume_independently_even_when_search_windows_exist(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    cutoff = start + timedelta(days=1)
    timeline_value = post(1, start + timedelta(hours=1))
    reply_values = [
        post(2, start + timedelta(hours=2), inReplyToTweetId=1),
        post(3, start + timedelta(hours=3), inReplyToTweetId=2),
    ]
    adapter = FakeAdapter(
        timeline=[timeline_value],
        replies=reply_values,
        searches={"from:alice": []},
        page_size=1,
        resolved_user=user(statuses_count=3),
    )
    db = Database(tmp_path / "jobs.db")
    service = UserExportService(
        adapter,
        db,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )
    job_id = db.create_job(
        username="alice",
        cutoff_at=cutoff,
        scope="authored",
        output_dir=tmp_path / "exports" / "alice" / "resume",
        start_at=start,
    )
    db.save_user_snapshot(job_id, UserSnapshot.from_object(user(statuses_count=3)).to_dict())
    db.add_windows(job_id, "search", [TimeWindow(start, cutoff)])

    timeline_scope = "timeline:user_tweets"
    service.pages.ensure_scope(job_id, timeline_scope, "user_tweets")
    timeline_page = CollectorPage(
        source="user_tweets",
        operation="UserTweets",
        request_cursor=None,
        next_cursor=None,
        items=(timeline_value,),
        raw_payload={"tweets": [timeline_value]},
        page_index=0,
    )
    timeline_artifact = service.raw_store.write_content_addressed_json(
        Path(job_id) / "pages" / "seed-timeline",
        timeline_page.artifact_payload(),
        prefix="page-000000",
    )
    service.pages.commit_page(
        job_id,
        timeline_scope,
        timeline_page,
        timeline_artifact,
        [PostRecord.from_object(timeline_value, source="user_tweets")],
    )
    service.pages.complete_scope(job_id, timeline_scope)

    reply_scope = "timeline:user_tweets_and_replies"
    service.pages.ensure_scope(job_id, reply_scope, "user_tweets_and_replies")
    reply_page = CollectorPage(
        source="user_tweets_and_replies",
        operation="UserTweetsAndReplies",
        request_cursor=None,
        next_cursor="offset:1",
        items=(reply_values[0],),
        raw_payload={"tweets": [reply_values[0]], "next_cursor": "offset:1"},
        page_index=0,
    )
    reply_artifact = service.raw_store.write_content_addressed_json(
        Path(job_id) / "pages" / "seed-replies",
        reply_page.artifact_payload(),
        prefix="page-000000",
    )
    service.pages.commit_page(
        job_id,
        reply_scope,
        reply_page,
        reply_artifact,
        [PostRecord.from_object(reply_values[0], source="user_tweets_and_replies")],
    )

    result = await service.export_user("alice", resume=True)

    assert not [request for request in adapter.page_requests if request[0] == "user_tweets"]
    reply_requests = [
        request for request in adapter.page_requests if request[0] == "user_tweets_and_replies"
    ]
    assert reply_requests[0][1] == "offset:1"
    assert {row["post_id"] for row in db.iter_posts(job_id)} == {"1", "2", "3"}
    assert result["page_count"] == 3
    assert service.pages.get_scope(job_id, timeline_scope)["state"] == "COMPLETE"
    assert service.pages.get_scope(job_id, reply_scope)["state"] == "COMPLETE"


@pytest.mark.asyncio
async def test_protected_target_stops_before_timeline_collection(tmp_path):
    adapter = FakeAdapter(resolved_user=user(protected=True, statuses_count=10))
    db = Database(tmp_path / "jobs.db")
    service = UserExportService(
        adapter,
        db,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )

    with pytest.raises(AuthRequired, match="protected"):
        await service.export_user(
            "alice",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            cutoff=datetime(2024, 1, 2, tzinfo=UTC),
        )

    job = db.list_jobs()[0]
    assert job["status"] == "HUMAN_REQUIRED"
    assert job["error_code"] == "AUTH_REQUIRED"
    assert adapter.page_requests == []


@pytest.mark.asyncio
async def test_unavailable_target_is_not_misclassified_as_schema_change(tmp_path):
    adapter = FakeAdapter(resolved_user=None)
    db = Database(tmp_path / "jobs.db")
    service = UserExportService(
        adapter,
        db,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )

    with pytest.raises(TargetUnavailable):
        await service.export_user(
            "missing-user",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            cutoff=datetime(2024, 1, 2, tzinfo=UTC),
        )

    job = db.list_jobs()[0]
    assert job["status"] == "FAILED"
    assert job["error_code"] == "TARGET_UNAVAILABLE"


@pytest.mark.asyncio
async def test_silently_empty_recent_and_search_surfaces_are_not_reported_complete(tmp_path):
    adapter = FakeAdapter(
        searches={"from:alice": []},
        resolved_user=user(statuses_count=4),
    )
    db = Database(tmp_path / "jobs.db")
    service = UserExportService(
        adapter,
        db,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )

    with pytest.raises(UpstreamChanged, match="returned no pages"):
        await service.export_user(
            "alice",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            cutoff=datetime(2024, 1, 2, tzinfo=UTC),
        )

    job = db.list_jobs()[0]
    assert job["status"] == "UPSTREAM_SCHEMA_CHANGED"
    assert job["coverage_status"] == "UPSTREAM_SCHEMA_CHANGED"


@pytest.mark.asyncio
async def test_resume_rejects_changed_fixed_start_and_cutoff(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    cutoff = datetime(2024, 1, 2, tzinfo=UTC)
    db = Database(tmp_path / "jobs.db")
    service = UserExportService(
        FakeAdapter(resolved_user=user(statuses_count=0)),
        db,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )
    db.create_job(
        username="alice",
        cutoff_at=cutoff,
        scope="authored",
        output_dir=tmp_path / "exports" / "alice" / "resume",
        start_at=start,
    )

    with pytest.raises(ValueError, match="change start"):
        await service.export_user("alice", start=start + timedelta(hours=1))
    with pytest.raises(ValueError, match="change cutoff"):
        await service.export_user("alice", cutoff=cutoff + timedelta(hours=1))


@pytest.mark.asyncio
async def test_historical_search_uses_resolved_username_and_stable_user_id(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    cutoff = start + timedelta(days=1)
    canonical_user = user(username="AliceCanonical", user_id=77, statuses_count=0)
    valid = post(1, start + timedelta(hours=1), username="AliceCanonical", user_id=77)
    reused_username = post(2, start + timedelta(hours=2), username="AliceCanonical", user_id=88)
    adapter = FakeAdapter(
        searches={"from:AliceCanonical": [valid, reused_username]},
        resolved_user=canonical_user,
    )
    db = Database(tmp_path / "jobs.db")
    service = UserExportService(
        adapter,
        db,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )

    result = await service.export_user("old_handle", start=start, cutoff=cutoff)

    assert adapter.queries
    assert all("from:AliceCanonical" in query for query in adapter.queries)
    assert result["username"] == "AliceCanonical"
    assert result["requested_username"] == "old_handle"
    assert {row["post_id"] for row in db.iter_posts(result["job_id"])} == {"1"}


@pytest.mark.asyncio
async def test_historical_search_enforces_half_open_window_at_ingestion(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    cutoff = start + timedelta(hours=2)
    at_start = post(1, start)
    inside = post(2, start + timedelta(hours=1))
    at_cutoff = post(3, cutoff)
    before = post(4, start - timedelta(seconds=1))
    foreign = post(5, start + timedelta(minutes=30), username="bob", user_id=8)
    adapter = FakeAdapter(
        searches={"from:alice": [before, at_start, foreign, inside, at_cutoff]},
        resolved_user=user(statuses_count=0),
        filter_search_by_query=False,
    )
    db = Database(tmp_path / "jobs.db")
    service = UserExportService(
        adapter,
        db,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )

    result = await service.export_user("alice", start=start, cutoff=cutoff)

    assert {row["post_id"] for row in db.iter_posts(result["job_id"])} == {"1", "2"}
    windows = [row for row in db.all_windows(result["job_id"]) if row["status"] != "SPLIT"]
    assert len(windows) == 1
    assert windows[0]["oldest_post_at"] == "2024-01-01T00:00:00Z"
    assert windows[0]["newest_post_at"] == "2024-01-01T01:00:00Z"


@pytest.mark.asyncio
async def test_dense_historical_window_splits_into_complete_contiguous_children(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    cutoff = start + timedelta(hours=4)
    values = [
        post(1, start + timedelta(minutes=30)),
        post(2, start + timedelta(minutes=60)),
        post(3, start + timedelta(minutes=90)),
        post(4, start + timedelta(minutes=150)),
        post(5, start + timedelta(minutes=180)),
        post(6, start + timedelta(minutes=210)),
    ]
    adapter = FakeAdapter(
        searches={"from:alice": values},
        page_size=2,
        resolved_user=user(statuses_count=0),
    )
    db = Database(tmp_path / "jobs.db")
    service = UserExportService(
        adapter,
        db,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )

    result = await service.export_user(
        "alice",
        start=start,
        cutoff=cutoff,
        min_window_seconds=3600,
        max_posts_per_window=3,
    )

    assert result["coverage_status"] == "COMPLETE_PUBLICLY_RETRIEVABLE"
    assert result["post_count"] == 6
    windows = db.all_windows(result["job_id"])
    parents = [row for row in windows if row["status"] == "SPLIT"]
    leaves = sorted(
        (row for row in windows if row["status"] == "COMPLETE"),
        key=lambda row: row["start_at"],
    )
    assert len(parents) == 1
    assert len(leaves) == 2
    assert leaves[0]["start_at"] == "2024-01-01T00:00:00Z"
    assert leaves[0]["end_at"] == leaves[1]["start_at"]
    assert leaves[1]["end_at"] == "2024-01-01T04:00:00Z"
    assert all(row["terminal_reason"] == "SOURCE_EXHAUSTED" for row in leaves)

    parent_scope = f"window:{parents[0]['window_id']}"
    assert service.pages.get_scope(result["job_id"], parent_scope)["state"] == "LIMIT_REACHED"
    assert service.pages.count_pages(result["job_id"]) >= 5


@pytest.mark.asyncio
async def test_export_rejects_fractional_second_contract_boundaries(tmp_path):
    db = Database(tmp_path / "jobs.db")
    service = UserExportService(
        FakeAdapter(resolved_user=user(statuses_count=0)),
        db,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )
    start = datetime(2024, 1, 1, microsecond=1, tzinfo=UTC)
    cutoff = datetime(2024, 1, 2, tzinfo=UTC)

    with pytest.raises(ValueError, match="start must use whole-second"):
        await service.export_user("alice", start=start, cutoff=cutoff)
    with pytest.raises(ValueError, match="cutoff must use whole-second"):
        await service.export_user(
            "alice",
            start=cutoff - timedelta(days=1),
            cutoff=cutoff.replace(microsecond=1),
            resume=False,
        )


@pytest.mark.asyncio
async def test_split_child_scope_resumes_from_its_own_committed_cursor(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    cutoff = start + timedelta(hours=4)
    left_values = [
        post(1, start + timedelta(minutes=30)),
        post(2, start + timedelta(minutes=90)),
    ]
    right_values = [
        post(3, start + timedelta(minutes=150)),
        post(4, start + timedelta(minutes=210)),
    ]
    adapter = FakeAdapter(
        searches={"from:alice": [*left_values, *right_values]},
        page_size=1,
        resolved_user=user(statuses_count=0),
    )
    db = Database(tmp_path / "jobs.db")
    service = UserExportService(
        adapter,
        db,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )
    job_id = db.create_job(
        username="alice",
        cutoff_at=cutoff,
        scope="authored",
        output_dir=tmp_path / "exports" / "alice" / "child-resume",
        start_at=start,
    )
    db.save_user_snapshot(job_id, UserSnapshot.from_object(user(statuses_count=0)).to_dict())

    parent = TimeWindow(start, cutoff)
    left, right = (
        TimeWindow(start, start + timedelta(hours=2), 1),
        TimeWindow(start + timedelta(hours=2), cutoff, 1),
    )
    db.add_windows(job_id, "search", [parent])
    parent_id = db.all_windows(job_id)[0]["window_id"]
    parent_scope = f"window:{parent_id}"
    service.pages.ensure_scope(job_id, parent_scope, "search")
    parent_page = CollectorPage(
        source="search",
        operation="SearchTimeline",
        request_cursor=None,
        next_cursor="seeded-parent-cursor",
        items=(),
        raw_payload={"tweets": [], "next_cursor": "seeded-parent-cursor"},
        page_index=0,
    )
    parent_artifact = service.raw_store.write_content_addressed_json(
        Path(job_id) / "pages" / "seed-parent",
        parent_page.artifact_payload(),
        prefix="page-000000",
    )
    service.pages.commit_page(
        job_id, parent_scope, parent_page, parent_artifact, []
    )
    service.pages.limit_scope(job_id, parent_scope, "SEEDED_SPLIT")
    db.update_window(parent_id, status="SPLIT", terminal_reason="SEEDED_SPLIT")
    db.add_windows(job_id, "search", [left, right])

    right_row = next(
        row
        for row in db.all_windows(job_id)
        if row["status"] == "PENDING" and row["start_at"] == "2024-01-01T02:00:00Z"
    )
    right_scope = f"window:{right_row['window_id']}"
    service.pages.ensure_scope(job_id, right_scope, "search")
    first_right = right_values[0]
    page = CollectorPage(
        source="search",
        operation="SearchTimeline",
        request_cursor=None,
        next_cursor="offset:1",
        items=(first_right,),
        raw_payload={"tweets": [first_right], "next_cursor": "offset:1"},
        page_index=0,
    )
    artifact = service.raw_store.write_content_addressed_json(
        Path(job_id) / "pages" / "seed-child",
        page.artifact_payload(),
        prefix="page-000000",
    )
    service.pages.commit_page(
        job_id,
        right_scope,
        page,
        artifact,
        [PostRecord.from_object(first_right, source="search")],
    )

    result = await service.export_user("alice", resume=True, max_posts_per_window=10)

    search_requests = [request for request in adapter.page_requests if request[0] == "search"]
    assert search_requests == [
        ("search", None, 10),
        ("search", "offset:1", 9),
    ]
    assert result["coverage_status"] == "COMPLETE_PUBLICLY_RETRIEVABLE"
    assert {row["post_id"] for row in db.iter_posts(job_id)} == {"1", "2", "3", "4"}
    assert service.pages.get_scope(job_id, right_scope)["state"] == "COMPLETE"
