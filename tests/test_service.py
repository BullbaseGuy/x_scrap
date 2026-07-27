from datetime import datetime, timedelta, timezone

import pytest

from fakes import FakeAdapter, post
from x_scrap.service import UserExportService
from x_scrap.storage.database import Database

UTC = timezone.utc


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
    assert result["coverage_status"] == "COMPLETE_PUBLICLY_RETRIEVABLE"
    output = tmp_path / "exports" / "alice" / result["job_id"]
    assert (output / "tweets.jsonl").is_file()
    assert (output / "coverage.json").is_file()
    assert db.count_posts(result["job_id"]) == 2


@pytest.mark.asyncio
async def test_saturated_window_is_split_until_source_exhausts(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    many = [post(i, start + timedelta(minutes=i)) for i in range(1, 4)]
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
async def test_resume_reuses_saved_profile_and_completed_windows(tmp_path):
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
    db.update_job(first["job_id"], status="PARTIAL")
    second = await service.export_user("alice", resume=True)
    assert second["job_id"] == first["job_id"]
    assert second["post_count"] == 1
