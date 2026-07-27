from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    infrastructure_retry_limit: int = 3
    same_root_cause_limit: int = 2
    rate_limit_retry_limit: int = 96
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    rate_limit_safety_seconds: float = 2.0
    minimum_rate_limit_delay_seconds: float = 1.0

    def delay_for_attempt(self, attempt: int) -> float:
        if attempt < 1:
            raise ValueError("attempt is one-based")
        return min(self.base_delay_seconds * (2 ** (attempt - 1)), self.max_delay_seconds)

    def rate_limit_delay(
        self,
        reset_at: datetime | None,
        *,
        now: datetime,
        fallback_attempt: int,
    ) -> float:
        if reset_at is None:
            return self.delay_for_attempt(fallback_attempt)
        current = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
        reset = (
            reset_at.replace(tzinfo=UTC)
            if reset_at.tzinfo is None
            else reset_at.astimezone(UTC)
        )
        return max(
            self.minimum_rate_limit_delay_seconds,
            (reset - current).total_seconds() + self.rate_limit_safety_seconds,
        )

    async def sleep(self, attempt: int) -> None:
        await asyncio.sleep(self.delay_for_attempt(attempt))
