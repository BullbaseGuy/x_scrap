import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fakes import FakeAdapter, post, user

from x_scrap.domain.pages import CollectorPage
from x_scrap.service import UserExportService
from x_scrap.storage.database import Database


@pytest.mark.asyncio
async def test_timeline_empty_page_guard_is_explicitly_truncated_and_search_stays_authoritative(
    tmp_path,
):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    cutoff = start + timedelta(days=1)
    value = post(1, start + timedelta(hours=1))

    class EmptyPageGuardAdapter(FakeAdapter):
        def iter_user_tweet_pages(
            self, user_id: str, *, cursor: str | None = None, limit: int = -1
        ):
            async def pages():
                self.page_requests.append(("user_tweets", cursor, limit))
                if cursor is None:
                    yield CollectorPage(
                        source="user_tweets",
                        operation="UserTweets",
                        request_cursor=None,
                        next_cursor="opaque-next-cursor",
                        items=(value,),
                        raw_payload={
                            "tweets": [value],
                            "instructions": [
                                {
                                    "cursorType": "Bottom",
                                    "value": "opaque-next-cursor",
                                }
                            ],
                        },
                    )

            return pages()

    adapter = EmptyPageGuardAdapter(
        searches={"from:alice": [value]},
        resolved_user=user(statuses_count=1),
    )
    database = Database(tmp_path / "jobs.db")
    service = UserExportService(
        adapter,
        database,
        exports_root=tmp_path / "exports",
        raw_root=tmp_path / "raw",
        heartbeat_interval=999,
    )
    result = await service.export_user("alice", start=start, cutoff=cutoff)

    scope = service.pages.get_scope(result["job_id"], "timeline:user_tweets")
    assert scope is not None
    assert scope["state"] == "LIMIT_REACHED"
    assert scope["last_error"] == "UPSTREAM_TIMELINE_CURSOR_REMAINS"
    assert result["coverage_status"] == "COMPLETE_PUBLICLY_RETRIEVABLE"
    assert result["post_count"] == 1

    events = database.list_events(result["job_id"])
    assert any(event["event_type"] == "TIMELINE_SOURCE_TRUNCATED" for event in events)
    coverage = json.loads(
        (Path(result["output_dir"]) / "coverage.json").read_text(encoding="utf-8")
    )
    assert coverage["timeline_truncated_sources"] == ["user_tweets"]
    assert any("empty-page guard" in warning for warning in coverage["warnings"])
