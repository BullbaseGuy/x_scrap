from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fakes import FakeAdapter, post

from x_scrap.domain.models import PostRecord, TimeWindow
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
