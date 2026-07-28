from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fakes import post

from x_scrap.audit.coverage import audit_collection, audit_coverage
from x_scrap.domain.models import PostRecord, TimeWindow
from x_scrap.domain.pages import CollectorPage
from x_scrap.storage.database import Database
from x_scrap.storage.page_repository import PageRepository
from x_scrap.storage.raw_store import RawStore


def _window_row(
    start: datetime,
    end: datetime,
    *,
    window_id: str,
    status: str = "COMPLETE",
) -> dict[str, object]:
    return {
        "window_id": window_id,
        "source": "search",
        "start_at": start.isoformat().replace("+00:00", "Z"),
        "end_at": end.isoformat().replace("+00:00", "Z"),
        "depth": 0,
        "status": status,
        "post_count": 0,
        "oldest_post_at": None,
        "newest_post_at": None,
        "terminal_reason": "SOURCE_EXHAUSTED",
    }


def test_exact_leaf_partition_rejects_gap_overlap_and_empty_input():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=4)
    middle = start + timedelta(hours=2)

    complete = audit_coverage(
        [
            _window_row(start, middle, window_id="left"),
            _window_row(middle, end, window_id="right"),
        ],
        start,
        end,
    )
    assert complete["status"] == "COMPLETE_PUBLICLY_RETRIEVABLE"

    gap = audit_coverage(
        [
            _window_row(start, middle, window_id="left"),
            _window_row(middle + timedelta(seconds=1), end, window_id="right"),
        ],
        start,
        end,
    )
    assert gap["status"] == "PARTIAL_UNRESOLVED_WINDOWS"
    assert gap["gaps"] == [
        {
            "start": "2026-01-01T02:00:00Z",
            "end": "2026-01-01T02:00:01Z",
        }
    ]

    overlap = audit_coverage(
        [
            _window_row(start, middle + timedelta(seconds=1), window_id="left"),
            _window_row(middle, end, window_id="right"),
        ],
        start,
        end,
    )
    assert overlap["status"] == "PARTIAL_UNRESOLVED_WINDOWS"
    assert overlap["overlaps"]

    empty = audit_coverage([], start, end)
    assert empty["status"] == "PARTIAL_UNRESOLVED_WINDOWS"
    assert empty["gaps"] == [{"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T04:00:00Z"}]


def _complete_evidence(tmp_path: Path):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=1)
    database = Database(tmp_path / "jobs.db")
    repository = PageRepository(database)
    raw_store = RawStore(tmp_path / "raw")
    job_id = database.create_job(
        username="alice",
        start_at=start,
        cutoff_at=end,
        scope="authored",
        output_dir=tmp_path / "out",
    )
    window = TimeWindow(start, end)
    database.add_windows(job_id, "search", [window])
    window_row = database.all_windows(job_id)[0]
    scope_key = f"window:{window_row['window_id']}"
    repository.ensure_scope(job_id, scope_key, "search")

    raw_post = post(1, start + timedelta(hours=1))
    page = CollectorPage(
        source="search",
        operation="SearchTimeline",
        request_cursor=None,
        next_cursor=None,
        items=(raw_post,),
        raw_payload={"tweets": [raw_post]},
        page_index=0,
    )
    artifact = raw_store.write_content_addressed_json(
        Path(job_id) / "pages" / "search",
        page.artifact_payload(),
        prefix="page-000000",
    )
    record = PostRecord.from_object(raw_post, source="search")
    repository.commit_page(job_id, scope_key, page, artifact, [record])
    repository.complete_scope(job_id, scope_key)
    database.update_window(
        window_row["window_id"],
        status="COMPLETE",
        post_count=1,
        oldest_post_at="2026-01-01T01:00:00Z",
        newest_post_at="2026-01-01T01:00:00Z",
        terminal_reason="SOURCE_EXHAUSTED",
    )
    return database, repository, raw_store, job_id, start, end, artifact.path


def _audit(database, repository, raw_store, job_id, start, end):
    return audit_collection(
        database.all_windows(job_id),
        start,
        end,
        scopes=repository.list_scopes(job_id),
        pages=repository.list_pages(job_id),
        page_links=repository.list_page_post_links(job_id),
        posts=list(database.iter_posts(job_id)),
        conflicts=database.list_post_conflicts(job_id),
        raw_root=raw_store.root,
    )


def test_cross_layer_audit_requires_valid_immutable_raw_evidence(tmp_path):
    database, repository, raw_store, job_id, start, end, artifact = _complete_evidence(tmp_path)

    valid = _audit(database, repository, raw_store, job_id, start, end)
    assert valid["status"] == "COMPLETE_PUBLICLY_RETRIEVABLE"
    assert valid["integrity"] == {
        "status": "PASS",
        "error_count": 0,
        "errors": [],
        "post_count": 1,
        "scope_count": 1,
        "page_count": 1,
        "page_link_count": 1,
        "raw_artifacts_checked": 1,
        "raw_artifacts_failed": 0,
    }

    artifact.unlink()
    invalid = _audit(database, repository, raw_store, job_id, start, end)
    assert invalid["status"] == "PARTIAL_UNRESOLVED_WINDOWS"
    assert invalid["integrity"]["status"] == "FAIL"
    assert {row["code"] for row in invalid["integrity"]["errors"]} == {
        "RAW_ARTIFACT_MISSING"
    }
