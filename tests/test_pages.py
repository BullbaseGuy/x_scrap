from datetime import UTC, datetime

import pytest

from x_scrap.domain.pages import CollectorPage


def test_collector_page_preserves_page_evidence_contract():
    captured = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    page = CollectorPage(
        source="search",
        operation="SearchTimeline",
        request_cursor=None,
        next_cursor="cursor-1",
        items=({"id": "1"},),
        raw_payload={"data": {"entries": [{"id": "1"}]}},
        page_index=0,
        captured_at=captured,
    )

    artifact = page.artifact_payload()
    assert artifact["schema_version"] == "1.0.0"
    assert artifact["request_cursor"] is None
    assert artifact["next_cursor"] == "cursor-1"
    assert artifact["parsed_item_count"] == 1
    assert artifact["captured_at"] == "2026-01-02T03:04:05Z"
    assert artifact["raw_payload"]["data"]["entries"][0]["id"] == "1"


def test_collector_page_rejects_non_advancing_cursor():
    with pytest.raises(ValueError, match="cursor did not advance"):
        CollectorPage(
            source="search",
            operation="SearchTimeline",
            request_cursor="same",
            next_cursor="same",
            items=(),
            raw_payload={},
        )
