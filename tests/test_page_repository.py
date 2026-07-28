from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fakes import post

from x_scrap.domain.models import PostRecord
from x_scrap.domain.pages import CollectorPage
from x_scrap.storage.database import Database
from x_scrap.storage.page_repository import PageRepository
from x_scrap.storage.raw_store import RawStore


def _job(database: Database, tmp_path: Path) -> str:
    return database.create_job(
        username="alice",
        cutoff_at=datetime(2026, 1, 3, tzinfo=UTC),
        scope="authored",
        output_dir=tmp_path / "out",
    )


def _page(
    *,
    index: int = 0,
    request_cursor: str | None = None,
    next_cursor: str | None = "cursor-1",
    raw_id: str = "1",
) -> CollectorPage:
    raw = post(int(raw_id), datetime(2026, 1, int(raw_id), tzinfo=UTC))
    return CollectorPage(
        source="search",
        operation="SearchTimeline",
        request_cursor=request_cursor,
        next_cursor=next_cursor,
        items=(raw,),
        raw_payload={"tweets": [raw], "cursor": next_cursor},
        page_index=index,
    )


def _artifact(store: RawStore, job_id: str, page: CollectorPage):
    return store.write_content_addressed_json(
        Path(job_id) / "pages" / "search",
        page.artifact_payload(),
        prefix=f"page-{page.page_index:06d}",
    )


def test_page_commit_is_idempotent_and_advances_resume_cursor(tmp_path):
    database = Database(tmp_path / "jobs.db")
    repository = PageRepository(database)
    store = RawStore(tmp_path / "raw")
    job_id = _job(database, tmp_path)
    scope_key = "window:search:one"
    repository.ensure_scope(job_id, scope_key, "search")

    page = _page()
    record = PostRecord.from_object(page.items[0], source="search")
    artifact = _artifact(store, job_id, page)

    assert repository.commit_page(job_id, scope_key, page, artifact, [record]) is True
    assert repository.commit_page(job_id, scope_key, page, artifact, [record]) is False

    scope = repository.get_scope(job_id, scope_key)
    assert scope is not None
    assert scope["state"] == "RUNNING"
    assert scope["next_cursor"] == "cursor-1"
    assert scope["next_page_index"] == 1
    assert database.count_posts(job_id) == 1

    pages = repository.list_pages(job_id, scope_key)
    assert len(pages) == 1
    assert pages[0]["payload_sha256"] == artifact.sha256
    assert pages[0]["artifact_size"] == artifact.size
    assert pages[0]["oldest_post_at"] == "2026-01-01T00:00:00Z"
    assert pages[0]["newest_post_at"] == "2026-01-01T00:00:00Z"
    assert repository.page_post_ids(job_id, scope_key, 0) == ["1"]

    stats = repository.scope_stats(job_id, scope_key)
    assert stats == {
        "page_count": 1,
        "item_count": 1,
        "accepted_count": 1,
        "oldest_post_at": "2026-01-01T00:00:00Z",
        "newest_post_at": "2026-01-01T00:00:00Z",
    }

    repository.complete_scope(job_id, scope_key)
    assert repository.get_scope(job_id, scope_key)["state"] == "COMPLETE"


def test_page_commit_rejects_cursor_and_payload_conflicts(tmp_path):
    database = Database(tmp_path / "jobs.db")
    repository = PageRepository(database)
    store = RawStore(tmp_path / "raw")
    job_id = _job(database, tmp_path)
    scope_key = "window:search:one"
    repository.ensure_scope(job_id, scope_key, "search")

    first = _page()
    first_record = PostRecord.from_object(first.items[0], source="search")
    repository.commit_page(job_id, scope_key, first, _artifact(store, job_id, first), [first_record])

    changed_same_index = _page(raw_id="2")
    changed_record = PostRecord.from_object(changed_same_index.items[0], source="search")
    with pytest.raises(ValueError, match="already has a different payload"):
        repository.commit_page(
            job_id,
            scope_key,
            changed_same_index,
            _artifact(store, job_id, changed_same_index),
            [changed_record],
        )

    wrong_cursor = _page(index=1, request_cursor="wrong", next_cursor=None, raw_id="2")
    wrong_record = PostRecord.from_object(wrong_cursor.items[0], source="search")
    with pytest.raises(ValueError, match="request cursor mismatch"):
        repository.commit_page(
            job_id,
            scope_key,
            wrong_cursor,
            _artifact(store, job_id, wrong_cursor),
            [wrong_record],
        )

    assert repository.count_pages(job_id) == 1
    assert database.count_posts(job_id) == 1
    assert repository.get_scope(job_id, scope_key)["next_page_index"] == 1


def test_page_commit_rolls_back_page_post_and_cursor_together(tmp_path, monkeypatch):
    database = Database(tmp_path / "jobs.db")
    repository = PageRepository(database)
    store = RawStore(tmp_path / "raw")
    job_id = _job(database, tmp_path)
    scope_key = "timeline:user_tweets"
    repository.ensure_scope(job_id, scope_key, "user_tweets")

    raw_one = post(1, datetime(2026, 1, 1, tzinfo=UTC))
    raw_two = post(2, datetime(2026, 1, 2, tzinfo=UTC))
    page = CollectorPage(
        source="user_tweets",
        operation="UserTweets",
        request_cursor=None,
        next_cursor="cursor-1",
        items=(raw_one, raw_two),
        raw_payload={"tweets": [raw_one, raw_two]},
        page_index=0,
    )
    records = [
        PostRecord.from_object(raw_one, source="user_tweets"),
        PostRecord.from_object(raw_two, source="user_tweets"),
    ]
    artifact = _artifact(store, job_id, page)

    original = PageRepository._upsert_post
    calls = 0

    def fail_after_first(conn, current_job_id, record, now):
        nonlocal calls
        calls += 1
        original(conn, current_job_id, record, now)
        if calls == 1:
            raise RuntimeError("synthetic interrupted transaction")

    monkeypatch.setattr(PageRepository, "_upsert_post", staticmethod(fail_after_first))
    with pytest.raises(RuntimeError, match="synthetic interrupted transaction"):
        repository.commit_page(job_id, scope_key, page, artifact, records)

    assert repository.count_pages(job_id) == 0
    assert database.count_posts(job_id) == 0
    scope = repository.get_scope(job_id, scope_key)
    assert scope["next_cursor"] is None
    assert scope["next_page_index"] == 0


def test_page_repository_migrates_existing_page_table(tmp_path):
    database = Database(tmp_path / "jobs.db")
    with database.connect() as conn:
        conn.executescript(
            """
            CREATE TABLE harvest_scopes (
                job_id TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                source TEXT NOT NULL,
                state TEXT NOT NULL,
                next_cursor TEXT,
                next_page_index INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(job_id, scope_key)
            );
            CREATE TABLE harvest_pages (
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
                captured_at TEXT NOT NULL,
                committed_at TEXT NOT NULL,
                PRIMARY KEY(job_id, scope_key, page_index)
            );
            """
        )

    PageRepository(database)

    with database.connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(harvest_pages)")}
        page_post_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='harvest_page_posts'"
        ).fetchone()
    assert {"oldest_post_at", "newest_post_at"}.issubset(columns)
    assert page_post_table is not None
