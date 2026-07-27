from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import AuthRequired, RateLimited, TransientUpstreamError, UpstreamChanged

_COOKIE_SECRET_RE = re.compile(r"(?i)(\b(?:auth_token|ct0)\s*=\s*)([^;\s]+)")
_REQUIRED_COOKIE_NAMES = ("auth_token", "ct0")


class TwscrapeAdapter:
    """Thin compatibility boundary around twscrape.

    All twscrape-specific imports, cookie handling, redaction, and exception
    heuristics live here so an upstream release can be repaired without
    changing the harvesting core.
    """

    def __init__(self, accounts_db: str | Path, *, proxy: str | None = None):
        _disable_upstream_telemetry()
        try:
            from twscrape import API
        except ImportError as exc:
            raise RuntimeError(
                "twscrape is not installed; install the project with `pip install -e .`"
            ) from exc
        self._api = API(str(accounts_db), proxy=proxy)

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
