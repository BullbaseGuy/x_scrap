from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc


def user(username: str = "alice", user_id: int = 7, created: datetime | None = None) -> dict[str, Any]:
    return {
        "id": user_id,
        "id_str": str(user_id),
        "username": username,
        "displayname": username.title(),
        "created": created or datetime(2024, 1, 1, tzinfo=UTC),
        "followersCount": 10,
        "statusesCount": 3,
        "url": f"https://x.com/{username}",
        "protected": False,
    }


def post(post_id: int, created: datetime, username: str = "alice", **extra: Any) -> dict[str, Any]:
    value = {
        "id": post_id,
        "id_str": str(post_id),
        "url": f"https://x.com/{username}/status/{post_id}",
        "date": created,
        "user": user(username=username),
        "lang": "en",
        "rawContent": f"post {post_id}",
        "conversationId": post_id,
        "replyCount": 0,
        "retweetCount": 0,
        "likeCount": 0,
        "quoteCount": 0,
        "bookmarkedCount": 0,
        "media": None,
    }
    value.update(extra)
    return value


class FakeAdapter:
    def __init__(self, timeline=None, replies=None, searches=None):
        self.timeline = timeline or []
        self.replies = replies or []
        self.searches = searches or {}
        self.queries: list[str] = []

    async def resolve_user(self, username: str):
        return user(username)

    async def iter_user_tweets(self, user_id: str, *, limit: int = -1):
        for value in self.timeline[: None if limit < 0 else limit]:
            yield value

    async def iter_user_tweets_and_replies(self, user_id: str, *, limit: int = -1):
        for value in self.replies[: None if limit < 0 else limit]:
            yield value

    async def iter_search(self, query: str, *, limit: int = -1):
        self.queries.append(query)
        for key, values in self.searches.items():
            if key in query:
                for value in values[: None if limit < 0 else limit]:
                    yield value
                return
