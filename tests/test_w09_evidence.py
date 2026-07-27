from __future__ import annotations

import json
import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fakes import post

from x_scrap.domain.models import PostRecord
from x_scrap.domain.pages import CollectorPage
from x_scrap.export.writer import write_export
from x_scrap.storage.database import Database
from x_scrap.storage.page_repository import PageRepository
from x_scrap.storage.raw_store import RawStore

build_evidence = runpy.run_path(
    str(Path(__file__).parents[1] / "scripts" / "live" / "collect_w09_evidence.py")
)["build_evidence"]


def _create_job(tmp_path: Path) -> tuple[Database, PageRepository, RawStore, str]:
    home = tmp_path / "state"
    database = Database(home / "jobs.db")
    pages = PageRepository(database)
    store = RawStore(home / "raw")
    job_id = database.create_job(
        username="alice",
        cutoff_at=datetime(2026, 1, 3, tzinfo=UTC),
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        scope="authored",
        output_dir=home / "exports" / "alice" / "job",
    )
    database.update_job(job_id, user_id="7", status="RUNNING")
    return database, pages, store, job_id


def _commit_page(
    database: Database,
    repository: PageRepository,
    store: RawStore,
    job_id: str,
    *,
    page_index: int,
    request_cursor: str | None,
    next_cursor: str | None,
) -> None:
    scope_key = "timeline:user_tweets"
    repository.ensure_scope(job_id, scope_key, "user_tweets")
    created = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=page_index)
    raw = post(page_index + 1, created)
    page = CollectorPage(
        source="user_tweets",
        operation="UserTweets",
        request_cursor=request_cursor,
        next_cursor=next_cursor,
        items=(raw,),
        raw_payload={"tweets": [raw], "auth_token": "should-not-survive"},
        page_index=page_index,
    )
    artifact = store.write_content_addressed_json(
        Path(job_id) / "pages" / scope_key.replace(":", "_"),
        page.artifact_payload(),
        prefix=f"page-{page_index:06d}",
    )
    record = PostRecord.from_object(raw, source="user_tweets")
    repository.commit_page(job_id, scope_key, page, artifact, [record])
    database.add_event(
        job_id,
        "PAGE_COMMITTED",
        {
            "scope_key": scope_key,
            "page_index": page_index,
            "payload_sha256": artifact.sha256,
        },
    )


def test_w09_evidence_reports_resume_boundaries_without_cursor_values(tmp_path):
    database, repository, store, job_id = _create_job(tmp_path)
    database.add_event(job_id, "JOB_STARTED", {"resume": False})
    _commit_page(
        database,
        repository,
        store,
        job_id,
        page_index=0,
        request_cursor=None,
        next_cursor="cursor-secret-1",
    )
    database.add_event(job_id, "JOB_STARTED", {"resume": True})
    _commit_page(
        database,
        repository,
        store,
        job_id,
        page_index=1,
        request_cursor="cursor-secret-1",
        next_cursor=None,
    )
    repository.complete_scope(job_id, "timeline:user_tweets")
    database.add_event(
        job_id,
        "RATE_LIMIT_WAIT",
        {
            "delay_seconds": 123,
            "reset_at": "2026-01-01T00:02:03Z",
            "authorization": "Bearer should-not-survive",
        },
    )

    evidence = build_evidence(tmp_path / "state", job_id)
    serialized = json.dumps(evidence, sort_keys=True)

    assert evidence["rate_limit_observed"] is True
    assert len(evidence["run_segments"]) == 2
    first = evidence["run_segments"][0]["last_committed_page"]
    resumed = evidence["run_segments"][1]["first_committed_page"]
    assert first["next_cursor_fingerprint"] == resumed["request_cursor_fingerprint"]
    assert "cursor-secret-1" not in serialized
    assert "should-not-survive" not in serialized
    assert "<redacted>" in serialized


def test_w09_evidence_verifies_finished_bundle(tmp_path):
    database, repository, store, job_id = _create_job(tmp_path)
    database.add_event(job_id, "JOB_STARTED", {"resume": False})
    _commit_page(
        database,
        repository,
        store,
        job_id,
        page_index=0,
        request_cursor=None,
        next_cursor=None,
    )
    repository.complete_scope(job_id, "timeline:user_tweets")
    database.update_job(
        job_id,
        status="COMPLETED",
        coverage_status="COMPLETE_PUBLICLY_RETRIEVABLE",
    )
    job = database.get_job(job_id)
    output = Path(job["output_dir"])
    write_export(
        output,
        manifest={
            "schema_version": "2.0.0",
            "job_id": job_id,
            "username": "alice",
            "start_at": "2026-01-01T00:00:00Z",
            "cutoff_at": "2026-01-03T00:00:00Z",
            "post_count": database.count_posts(job_id),
            "page_count": repository.count_pages(job_id),
        },
        profile={"user_id": "7", "username": "alice"},
        coverage={
            "schema_version": "2.0.0",
            "status": "COMPLETE_PUBLICLY_RETRIEVABLE",
            "integrity": {"status": "PASS"},
            "known_source_limitations": [],
        },
        posts=database.iter_posts(job_id),
        events=database.list_events(job_id),
        conflicts=[],
        scopes=repository.list_scopes(job_id),
        windows=[],
        pages=repository.list_pages(job_id),
        raw_root=store.root,
    )

    evidence = build_evidence(tmp_path / "state", job_id)
    assert evidence["bundle"]["verified"] is True
    assert evidence["bundle"]["bundle_digest"]
    assert evidence["counts"]["posts"] == 1
