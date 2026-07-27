from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

UTC = UTC


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_RATE_LIMIT = "WAITING_RATE_LIMIT"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    UPSTREAM_SCHEMA_CHANGED = "UPSTREAM_SCHEMA_CHANGED"


class WindowStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    SPLIT = "SPLIT"
    PARTIAL_LIMIT_REACHED = "PARTIAL_LIMIT_REACHED"
    FAILED = "FAILED"


class CoverageStatus(StrEnum):
    COMPLETE_PUBLICLY_RETRIEVABLE = "COMPLETE_PUBLICLY_RETRIEVABLE"
    COMPLETE_WITH_KNOWN_SOURCE_LIMITATIONS = "COMPLETE_WITH_KNOWN_SOURCE_LIMITATIONS"
    PARTIAL_UNRESOLVED_WINDOWS = "PARTIAL_UNRESOLVED_WINDOWS"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    UPSTREAM_SCHEMA_CHANGED = "UPSTREAM_SCHEMA_CHANGED"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def iso_utc(value: datetime | None) -> str | None:
    return ensure_utc(value).isoformat().replace("+00:00", "Z") if value else None


def parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return ensure_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return iso_utc(value)
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {k: jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    return value


def object_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    method = getattr(value, "dict", None)
    if callable(method):
        result = method()
        if isinstance(result, Mapping):
            return dict(result)
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"cannot convert {type(value)!r} to mapping")


def _id(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, Mapping):
        value = value.get("id_str", value.get("id"))
    return str(value) if value is not None else None


@dataclass(frozen=True, slots=True)
class UserSnapshot:
    user_id: str
    username: str
    display_name: str
    created_at: datetime | None
    protected: bool | None
    followers_count: int | None
    statuses_count: int | None
    profile_url: str | None
    description: str | None
    captured_at: datetime
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_object(cls, value: Any) -> UserSnapshot:
        data = object_mapping(value)
        user_id = _id(data.get("user_id", data.get("id_str", data.get("id"))))
        username = str(data.get("username") or data.get("screen_name") or "").lstrip("@")
        if not user_id or not username:
            raise ValueError("upstream user object is missing id or username")
        raw_value = data.get("raw")
        raw = jsonable(raw_value) if isinstance(raw_value, Mapping) else jsonable(data)
        return cls(
            user_id=user_id,
            username=username,
            display_name=str(
                data.get("display_name") or data.get("displayname") or data.get("name") or ""
            ),
            created_at=parse_datetime(data.get("created_at") or data.get("created")),
            protected=data.get("protected"),
            followers_count=_safe_int(
                data.get("followers_count", data.get("followersCount"))
            ),
            statuses_count=_safe_int(
                data.get("statuses_count", data.get("statusesCount"))
            ),
            profile_url=data.get("profile_url") or data.get("url") or f"https://x.com/{username}",
            description=data.get("description") or data.get("rawDescription"),
            captured_at=parse_datetime(data.get("captured_at")) or utc_now(),
            raw=raw,
        )

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class PostRecord:
    post_id: str
    user_id: str
    username: str
    created_at: datetime
    text: str
    url: str
    conversation_id: str | None
    in_reply_to_post_id: str | None
    quoted_post_id: str | None
    reposted_post_id: str | None
    language: str | None
    is_reply: bool
    is_quote: bool
    is_retweet: bool
    metrics: dict[str, int | None]
    media: dict[str, Any] | None
    source: str
    captured_at: datetime
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_object(cls, value: Any, *, source: str) -> PostRecord:
        data = object_mapping(value)
        user = data.get("user") or {}
        if not isinstance(user, Mapping):
            user = object_mapping(user)
        post_id = _id(data.get("id_str", data.get("id")))
        user_id = _id(user.get("id_str", user.get("id")))
        username = str(user.get("username") or user.get("screen_name") or "").lstrip("@")
        created_at = parse_datetime(data.get("date") or data.get("created_at"))
        if not post_id or not user_id or not username or created_at is None:
            raise ValueError("upstream post object is missing required identity or timestamp fields")
        quoted = data.get("quotedTweet") or data.get("quoted_tweet")
        reposted = data.get("retweetedTweet") or data.get("retweeted_tweet")
        reply_id = _id(data.get("inReplyToTweetIdStr", data.get("inReplyToTweetId")))
        quoted_id = _id(quoted)
        reposted_id = _id(reposted)
        return cls(
            post_id=post_id,
            user_id=user_id,
            username=username,
            created_at=created_at,
            text=str(data.get("rawContent") or data.get("full_text") or data.get("text") or ""),
            url=str(data.get("url") or f"https://x.com/{username}/status/{post_id}"),
            conversation_id=_id(data.get("conversationIdStr", data.get("conversationId"))),
            in_reply_to_post_id=reply_id,
            quoted_post_id=quoted_id,
            reposted_post_id=reposted_id,
            language=data.get("lang"),
            is_reply=reply_id is not None,
            is_quote=bool(data.get("isQuoteStatus") or quoted_id),
            is_retweet=reposted_id is not None,
            metrics={
                "reply_count": _safe_int(data.get("replyCount", data.get("reply_count"))),
                "retweet_count": _safe_int(data.get("retweetCount", data.get("retweet_count"))),
                "like_count": _safe_int(data.get("likeCount", data.get("favorite_count"))),
                "quote_count": _safe_int(data.get("quoteCount", data.get("quote_count"))),
                "bookmark_count": _safe_int(data.get("bookmarkedCount", data.get("bookmark_count"))),
                "view_count": _safe_int(data.get("viewCount", data.get("view_count"))),
            },
            media=jsonable(data.get("media")) if data.get("media") is not None else None,
            source=source,
            captured_at=utc_now(),
            raw=jsonable(data),
        )

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class TimeWindow:
    start: datetime
    end: datetime
    depth: int = 0

    def __post_init__(self) -> None:
        start = ensure_utc(self.start)
        end = ensure_utc(self.end)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        if start >= end:
            raise ValueError("window start must precede end")

    @property
    def duration_seconds(self) -> int:
        return int((self.end - self.start).total_seconds())

    @property
    def key(self) -> str:
        return f"{int(self.start.timestamp())}-{int(self.end.timestamp())}"

    def to_dict(self) -> dict[str, Any]:
        return {"start": iso_utc(self.start), "end": iso_utc(self.end), "depth": self.depth}
