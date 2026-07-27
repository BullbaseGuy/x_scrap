from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Protocol

from x_scrap.domain.pages import CollectorPage


class AdapterError(RuntimeError):
    """Base class for upstream adapter failures."""


class AuthRequired(AdapterError):
    """The local account session is missing, expired, or challenged."""


class RateLimited(AdapterError):
    def __init__(self, message: str, reset_at: datetime | None = None):
        super().__init__(message)
        self.reset_at = reset_at


class TargetUnavailable(AdapterError):
    """The requested username is missing, suspended, or otherwise unavailable."""


class UpstreamChanged(AdapterError):
    """The upstream GraphQL schema or operation surface changed."""


class TransientUpstreamError(AdapterError):
    """A retryable network or upstream failure."""


class CollectorAdapter(Protocol):
    async def resolve_user(self, username: str) -> Any: ...

    def iter_user_tweet_pages(
        self, user_id: str, *, cursor: str | None = None, limit: int = -1
    ) -> AsyncIterator[CollectorPage]: ...

    def iter_user_tweet_and_reply_pages(
        self, user_id: str, *, cursor: str | None = None, limit: int = -1
    ) -> AsyncIterator[CollectorPage]: ...

    def iter_search_pages(
        self, query: str, *, cursor: str | None = None, limit: int = -1
    ) -> AsyncIterator[CollectorPage]: ...
