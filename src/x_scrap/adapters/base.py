from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Protocol


class AdapterError(RuntimeError):
    """Base class for upstream adapter failures."""


class AuthRequired(AdapterError):
    """The local account session is missing, expired, or challenged."""


class RateLimited(AdapterError):
    def __init__(self, message: str, reset_at: datetime | None = None):
        super().__init__(message)
        self.reset_at = reset_at


class UpstreamChanged(AdapterError):
    """The upstream GraphQL schema or operation surface changed."""


class TransientUpstreamError(AdapterError):
    """A retryable network or upstream failure."""


class CollectorAdapter(Protocol):
    async def resolve_user(self, username: str) -> Any: ...

    def iter_user_tweets(self, user_id: str, *, limit: int = -1) -> AsyncIterator[Any]: ...

    def iter_user_tweets_and_replies(
        self, user_id: str, *, limit: int = -1
    ) -> AsyncIterator[Any]: ...

    def iter_search(self, query: str, *, limit: int = -1) -> AsyncIterator[Any]: ...
