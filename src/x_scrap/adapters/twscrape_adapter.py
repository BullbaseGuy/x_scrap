from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from x_scrap.domain.pages import CollectorPage

from .base import AuthRequired, RateLimited, TransientUpstreamError, UpstreamChanged

_COOKIE_SECRET_RE = re.compile(r"(?i)(\b(?:auth_token|ct0)\s*=\s*)([^;\s]+)")
_REQUIRED_COOKIE_NAMES = ("auth_token", "ct0")


class TwscrapeAdapter:
    """Thin compatibility boundary around twscrape.

    All twscrape-specific imports, cookie handling, redaction, pagination,
    and exception heuristics live here so an upstream release can be repaired
    without changing the harvesting core.
    """

    def __init__(self, accounts_db: str | Path, *, proxy: str | None = None):
        _disable_upstream_telemetry()
        try:
            from twscrape import API
            from twscrape.models import parse_tweets
        except ImportError as exc:
            raise RuntimeError(
                "twscrape is not installed; install the project with `pip install -e .`"
            ) from exc
        self._api = API(str(accounts_db), proxy=proxy)
        self._parse_tweets = parse_tweets

    async def add_cookie(self, label: str, cookie_header: str) -> None:
        label = label.strip()
        if not label or "\n" in label or "\r" in label:
            raise ValueError("account label must be a non-empty single line")
        _validate_cookie(cookie_header)
        await self._api.pool.add_account_cookies(label, cookie_header)

    async def list_accounts(self) -> list[dict[str, Any]]:
        accounts = await self._api.pool.get_all()
        return [
            {
                "username": str(account.username),
                "active": bool(account.active),
                "last_used": str(account.last_used) if account.last_used else None,
                "error_msg": _redact_secret_text(account.error_msg),
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

    async def iter_user_tweet_pages(
        self, user_id: str, *, cursor: str | None = None, limit: int = -1
    ) -> AsyncIterator[CollectorPage]:
        values = {"cursor": cursor} if cursor else None
        stream = self._api.user_tweets_raw(int(user_id), limit=limit, kv=values)
        async for page in self._guarded_pages(
            stream,
            source="user_tweets",
            operation="UserTweets",
            initial_cursor=cursor,
        ):
            yield page

    async def iter_user_tweet_and_reply_pages(
        self, user_id: str, *, cursor: str | None = None, limit: int = -1
    ) -> AsyncIterator[CollectorPage]:
        values = {"cursor": cursor} if cursor else None
        stream = self._api.user_tweets_and_replies_raw(int(user_id), limit=limit, kv=values)
        async for page in self._guarded_pages(
            stream,
            source="user_tweets_and_replies",
            operation="UserTweetsAndReplies",
            initial_cursor=cursor,
        ):
            yield page

    async def iter_search_pages(
        self, query: str, *, cursor: str | None = None, limit: int = -1
    ) -> AsyncIterator[CollectorPage]:
        values = {"cursor": cursor} if cursor else None
        stream = self._api.search_raw(query, limit=limit, kv=values)
        async for page in self._guarded_pages(
            stream,
            source="search",
            operation="SearchTimeline",
            initial_cursor=cursor,
        ):
            yield page

    async def iter_user_tweets(self, user_id: str, *, limit: int = -1) -> AsyncIterator[Any]:
        async for page in self.iter_user_tweet_pages(user_id, limit=limit):
            for item in page.items:
                yield item

    async def iter_user_tweets_and_replies(
        self, user_id: str, *, limit: int = -1
    ) -> AsyncIterator[Any]:
        async for page in self.iter_user_tweet_and_reply_pages(user_id, limit=limit):
            for item in page.items:
                yield item

    async def iter_search(self, query: str, *, limit: int = -1) -> AsyncIterator[Any]:
        async for page in self.iter_search_pages(query, limit=limit):
            for item in page.items:
                yield item

    async def _guarded_pages(
        self,
        stream: AsyncIterator[Any],
        *,
        source: str,
        operation: str,
        initial_cursor: str | None,
    ) -> AsyncIterator[CollectorPage]:
        try:
            async for page in self._iter_pages(
                stream,
                source=source,
                operation=operation,
                initial_cursor=initial_cursor,
            ):
                yield page
        except (AuthRequired, RateLimited, TransientUpstreamError, UpstreamChanged):
            raise
        except Exception as exc:
            raise _classify(exc) from exc

    async def _iter_pages(
        self,
        stream: AsyncIterator[Any],
        *,
        source: str,
        operation: str,
        initial_cursor: str | None,
    ) -> AsyncIterator[CollectorPage]:
        request_cursor = initial_cursor
        seen_cursors = {initial_cursor} if initial_cursor else set()
        page_index = 0
        async for response in stream:
            payload = response.json()
            if not isinstance(payload, dict):
                raise UpstreamChanged(f"{operation} returned a non-object JSON payload")
            next_cursor = _bottom_cursor(payload)
            if next_cursor is not None and next_cursor in seen_cursors:
                raise UpstreamChanged(f"{operation} returned a repeated pagination cursor")
            if next_cursor is not None:
                seen_cursors.add(next_cursor)
            try:
                items = tuple(self._parse_tweets(payload, -1))
            except Exception as exc:
                raise UpstreamChanged(f"{operation} response parsing failed: {exc}") from exc
            yield CollectorPage(
                source=source,
                operation=operation,
                request_cursor=request_cursor,
                next_cursor=next_cursor,
                items=items,
                raw_payload=payload,
                page_index=page_index,
            )
            request_cursor = next_cursor
            page_index += 1


def _disable_upstream_telemetry() -> None:
    # Assign rather than setdefault so a parent shell cannot accidentally
    # re-enable telemetry for this process.
    os.environ["TWS_TELEMETRY"] = "0"
    os.environ["DO_NOT_TRACK"] = "1"


def _validate_cookie(cookie_header: str) -> None:
    if not isinstance(cookie_header, str):
        raise TypeError("cookie header must be a string")
    if "\n" in cookie_header or "\r" in cookie_header:
        raise ValueError("cookie header must be a single line")

    values: dict[str, str] = {}
    for segment in cookie_header.split(";"):
        name, separator, value = segment.strip().partition("=")
        if separator:
            values[name.strip().lower()] = value.strip()

    missing = [name for name in _REQUIRED_COOKIE_NAMES if not values.get(name)]
    if missing:
        raise ValueError("cookie header must contain non-empty auth_token and ct0 values")


def _redact_secret_text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    return _COOKIE_SECRET_RE.sub(lambda match: f"{match.group(1)}<redacted>", text)


def _bottom_cursor(payload: dict[str, Any]) -> str | None:
    cursor = _find_cursor_type(payload, "Bottom")
    if cursor is not None:
        return cursor
    return _find_named_cursor(payload, "next_cursor")


def _find_cursor_type(value: Any, cursor_type: str) -> str | None:
    if isinstance(value, dict):
        if value.get("cursorType") == cursor_type:
            cursor = value.get("value")
            if isinstance(cursor, str) and cursor:
                return cursor
        for child in value.values():
            cursor = _find_cursor_type(child, cursor_type)
            if cursor is not None:
                return cursor
    elif isinstance(value, list):
        for child in value:
            cursor = _find_cursor_type(child, cursor_type)
            if cursor is not None:
                return cursor
    return None


def _find_named_cursor(value: Any, key: str) -> str | None:
    if isinstance(value, dict):
        cursor = value.get(key)
        if isinstance(cursor, str) and cursor:
            return cursor
        for child in value.values():
            cursor = _find_named_cursor(child, key)
            if cursor is not None:
                return cursor
    elif isinstance(value, list):
        for child in value:
            cursor = _find_named_cursor(child, key)
            if cursor is not None:
                return cursor
    return None


def _reset_at(exc: Exception) -> datetime | None:
    for attribute in ("reset_at", "unlock_at", "reset"):
        value = getattr(exc, attribute, None)
        if isinstance(value, datetime):
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        if isinstance(value, (int, float)) and value > 0:
            timestamp = value / 1000 if value > 10_000_000_000 else value
            try:
                return datetime.fromtimestamp(timestamp, UTC)
            except (OverflowError, OSError, ValueError):
                continue
    return None


def _classify(exc: Exception) -> Exception:
    name = type(exc).__name__.lower()
    message = _redact_secret_text(str(exc)) or type(exc).__name__
    lowered = message.lower()
    if "rate" in name or "429" in lowered or "rate limit" in lowered:
        return RateLimited(message, reset_at=_reset_at(exc))
    if "noaccount" in name or any(
        token in lowered
        for token in ("login", "unauthorized", "forbidden", "challenge", "cookie")
    ):
        return AuthRequired(message)
    if any(token in lowered for token in ("operation", "graphql", "transaction id", "not found")) and (
        "404" in lowered or "unknown" in lowered or "missing" in lowered
    ):
        return UpstreamChanged(message)
    if any(token in lowered for token in ("timeout", "temporar", "502", "503", "504", "connection")):
        return TransientUpstreamError(message)
    return UpstreamChanged(message)
