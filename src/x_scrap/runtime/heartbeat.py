from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import suppress


class Heartbeat:
    def __init__(
        self,
        snapshot: Callable[[], dict[str, object]],
        *,
        interval_seconds: float = 45.0,
        emit: Callable[[str], None] = print,
    ):
        self._snapshot = snapshot
        self._interval = interval_seconds
        self._emit = emit
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "Heartbeat":
        self._task = asyncio.create_task(self._run())
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            self._emit(json.dumps(self._snapshot(), ensure_ascii=False, sort_keys=True))
