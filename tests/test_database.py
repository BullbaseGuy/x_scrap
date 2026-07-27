from datetime import datetime, timezone

from fakes import post
from x_scrap.domain.models import PostRecord
from x_scrap.storage.database import Database

UTC = timezone.utc


def test_post_upsert_is_idempotent_and_merges_sources(tmp_path):
    db = Database(tmp_path / "jobs.db")
    job = db.create_job(
        username="alice",
        cutoff_at=datetime(2026, 1, 2, tzinfo=UTC),
        scope="authored",
        output_dir=tmp_path / "out",
    )
    first = PostRecord.from_object(post(1, datetime(2026, 1, 1, tzinfo=UTC)), source="timeline")
    second = PostRecord.from_object(post(1, datetime(2026, 1, 1, tzinfo=UTC)), source="search")
    assert db.upsert_post(job, first) is True
    assert db.upsert_post(job, second) is False
    assert db.count_posts(job) == 1
    stored = list(db.iter_posts(job))[0]
    assert stored["sources"] == ["search", "timeline"]
