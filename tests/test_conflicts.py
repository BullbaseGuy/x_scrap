from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fakes import FakeAdapter, post, user

from x_scrap.domain.models import PostRecord
from x_scrap.service import UserExportService
from x_scrap.storage.database import Database


def test_same_id_material_conflict_is_persisted_without_replacing_canonical_payload(tmp_path):
    created = datetime(2026, 1, 1, tzinfo=UTC)
    database = Database(tmp_path / "jobs.db")
    job_id = database.create_job(
        username="alice",
        start_at=created,
        cutoff_at=created + timedelta(days=1),
        scope="authored",
        output_dir=tmp_path / "out",
    )
    canonical = PostRecord.from_object(post(1, created, rawContent="canonical"), source="user_tweets")
    observed = PostRecord.from_object(post(1, created, rawContent="changed"), source="search")

    assert database.upsert_post(job_id, canonical) is True
    assert database.upsert_post(job_id, observed) is False

    stored = list(database.iter_posts(job_id))[0]
    assert stored["text"] == "canonical"
    assert stored["sources"] == ["search", "user_tweets"]
    conflicts = database.list_post_conflicts(job_id)
    assert len(conflicts) == 1
    assert conflicts[0]["post_id"] == "1"
    assert conflicts[0]["canonical_material"]["text"] == "canonical"
    assert conflicts[0]["observed_material"]["text"] == "changed"


@pytest.mark.asyncio
async def test_service_exposes_source_conflict_and_writes_conflict_evidence(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    canonical = post(1, start + timedelta(hours=1), rawContent="canonical")
    changed = post(1, start + timedelta(hours=1), rawContent="changed")
    adapter = FakeAdapter(
        timeline=[canonical],
        replies=[],
        searches={"from:alice": [changed]},
        resolved_user=user(created=start, statuses_count=1),
    )
    database = Database(tmp_path / "jobs.db")
    service = UserExportService(
        adapter,
        database,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )

    result = await service.export_user(
        "alice",
        start=start,
        cutoff=start + timedelta(days=1),
        max_posts_per_window=100,
    )

    assert result["coverage_status"] == "SOURCE_CONFLICT"
    assert result["conflict_count"] == 1
    assert database.get_job(result["job_id"])["status"] == "PARTIAL"
    output = tmp_path / "exports" / "alice" / result["job_id"]
    conflict_text = (output / "conflicts.jsonl").read_text(encoding="utf-8")
    assert '"post_id":"1"' in conflict_text
    assert '"canonical"' in conflict_text
    assert '"changed"' in conflict_text
