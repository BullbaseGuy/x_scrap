from datetime import UTC, datetime
from pathlib import Path

from fakes import post

from x_scrap.domain.models import PostRecord
from x_scrap.domain.pages import CollectorPage
from x_scrap.storage.database import Database
from x_scrap.storage.page_repository import PageRepository
from x_scrap.storage.raw_store import RawStore


def test_scope_statistics_count_unique_posts_across_pages(tmp_path):
    database = Database(tmp_path / "jobs.db")
    repository = PageRepository(database)
    raw_store = RawStore(tmp_path / "raw")
    job_id = database.create_job(
        username="alice",
        cutoff_at=datetime(2026, 1, 2, tzinfo=UTC),
        scope="authored",
        output_dir=tmp_path / "out",
    )
    scope_key = "window:dedupe"
    repository.ensure_scope(job_id, scope_key, "search")
    value = post(1, datetime(2026, 1, 1, tzinfo=UTC))
    record = PostRecord.from_object(value, source="search")

    pages = [
        CollectorPage(
            source="search",
            operation="SearchTimeline",
            request_cursor=None,
            next_cursor="offset:1",
            items=(value,),
            raw_payload={"page": 0, "tweets": [value]},
            page_index=0,
        ),
        CollectorPage(
            source="search",
            operation="SearchTimeline",
            request_cursor="offset:1",
            next_cursor=None,
            items=(value,),
            raw_payload={"page": 1, "tweets": [value]},
            page_index=1,
        ),
    ]
    for page in pages:
        artifact = raw_store.write_content_addressed_json(
            Path(job_id) / "pages" / "dedupe",
            page.artifact_payload(),
            prefix=f"page-{page.page_index:06d}",
        )
        repository.commit_page(job_id, scope_key, page, artifact, [record])

    stats = repository.scope_stats(job_id, scope_key)
    assert stats["page_count"] == 2
    assert stats["item_count"] == 2
    assert stats["accepted_count"] == 1
    assert database.count_posts(job_id) == 1
    assert repository.page_post_ids(job_id, scope_key, 0) == ["1"]
    assert repository.page_post_ids(job_id, scope_key, 1) == ["1"]
