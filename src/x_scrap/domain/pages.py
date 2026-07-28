from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .models import ensure_utc, iso_utc, jsonable, utc_now


@dataclass(frozen=True, slots=True)
class CollectorPage:
    """One committed upstream page and the cursor needed to continue after it."""

    source: str
    operation: str
    request_cursor: str | None
    next_cursor: str | None
    items: tuple[Any, ...]
    raw_payload: dict[str, Any]
    page_index: int = 0
    captured_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.source or not self.operation:
            raise ValueError("page source and operation are required")
        if self.page_index < 0:
            raise ValueError("page index cannot be negative")
        if self.request_cursor is not None and self.request_cursor == self.next_cursor:
            raise ValueError("page cursor did not advance")
        object.__setattr__(self, "captured_at", ensure_utc(self.captured_at))
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "raw_payload", jsonable(self.raw_payload))

    def artifact_payload(self) -> dict[str, Any]:
        """Return only the stable upstream payload stored as raw evidence."""

        return dict(self.raw_payload)

    def metadata_payload(self) -> dict[str, Any]:
        """Return page metadata persisted in SQLite, not duplicated into raw evidence."""

        return {
            "schema_version": "1.0.0",
            "source": self.source,
            "operation": self.operation,
            "page_index": self.page_index,
            "request_cursor": self.request_cursor,
            "next_cursor": self.next_cursor,
            "captured_at": iso_utc(self.captured_at),
            "parsed_item_count": len(self.items),
        }
