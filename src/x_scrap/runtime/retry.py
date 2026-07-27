from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    infrastructure_retry_limit: int = 3
    same_root_cause_limit: int = 2
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0

    def delay_for_attempt(self, attempt: int) -> float:
        if attempt < 1:
            raise ValueError("attempt is one-based")
        return min(self.base_delay_seconds * (2 ** (attempt - 1)), self.max_delay_seconds)

    async def sleep(self, attempt: int) -> None:
        await asyncio.sleep(self.delay_for_attempt(attempt))
