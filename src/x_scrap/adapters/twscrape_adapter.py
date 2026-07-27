from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from .base import AuthRequired, RateLimited, TransientUpstreamError, UpstreamChanged


class TwscrapeAdapter:
    """Thin compatibility boundary around twscrape.

    All twscrape-specific imports and exception heuristics live here so an
    upstream release can be repaired without changing the harvesting core.
    """

    def __init__(self, accounts_db: str | Path, *, proxy: str | None = None):
        os.environ.setdefault("TWS_TELEMETRY", "0")
        try:
            from twscrape import API
        except ImportError as exc:
            raise RuntimeError(
                "twscrape is not installed; install the project with `pip install -e .`"
            ) from exc
        self._api = API(str(accounts_db), proxy=proxy)

    async def add_cookie(self, label: str, cookie_header: str) -> None:
        _validate_cookie(cookie_header)
        await self._api.pool.add_account_cookies(label, cookie_header)

    async def list_accounts(self) -> list[dict[str, Any]]:
        accounts = await self._api.pool.get_all()
        return [
            {
                "username": account.username,
                "active": bool(account.active),
                "last_used": str(account.last_used) if account.last_used else None,
                "error_msg": account.error_msg,
            }
            for account in accounts
        ]

    async def resolve_user(self, username: str) -> Any:
        try:
            result = await self._api.user_by_login(username.lstrip("@"))
        except Exception as exc:  # upstream exception types are not stable
            raise _classify(exc) from exc
        if result is None:
            raise UpstreamChanged(f"no user payload returned for @{username.lstrip('@')}")
        return result

    async def iter_user_tweets(self, user_id: str, *, limit: int = -1) -> AsyncIterator[Any]:
        try:
            async for item in self._api.user_tweets(int(user_id), limit=limit):
                yield item
        except Exception as exc:
            raise _classify(exc) from exc

    async def iter_user_tweets_and_replies(
        self, user_id: str, *, limit: int = -1
    ) -> AsyncIterator[Any]:
        try:
            async for item in self._api.user_tweets_and_replies(int(user_id), limit=limit):
                yield item
        except Exception as exc:
            raise _classify(exc) from exc

    async def iter_search(self, query: str, *, limit: int = -1) -> AsyncIterator[Any]:
        try:
            async for item in self._api.search(query, limit=limit):
                yield item
        except Exception as exc:
            raise _classify(exc) from exc


def _validate_cookie(cookie_header: str) -> None:
    lowered = cookie_header.lower()
    missing = [name for name in ("auth_token=", "ct0=") if name not in lowered]
    if missing:
        raise ValueError("cookie header must contain auth_token and ct0")
    if "\n" in cookie_header or "\r" in cookie_header:
        raise ValueError("cookie header must be a single line")


def _classify(exc: Exception) -> Exception:
    name = type(exc).__name__.lower()
    message = str(exc)
    lowered = message.lower()
    if "rate" in name or "429" in lowered or "rate limit" in lowered:
        return RateLimited(message or type(exc).__name__)
    if any(token in lowered for token in ("login", "unauthorized", "forbidden", "challenge", "cookie")):
        return AuthRequired(message or type(exc).__name__)
    if any(token in lowered for token in ("operation", "graphql", "transaction id", "not found")) and (
        "404" in lowered or "unknown" in lowered or "missing" in lowered
    ):
        return UpstreamChanged(message or type(exc).__name__)
    if any(token in lowered for token in ("timeout", "temporar", "502", "503", "504", "connection")):
        return TransientUpstreamError(message or type(exc).__name__)
    return UpstreamChanged(message or type(exc).__name__)
