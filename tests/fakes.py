from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from x_scrap.domain.pages import CollectorPage

UTC = UTC


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
    def __init__(self, timeline=None, replies=None, searches=None, *, page_size: int = 100):
        self.timeline = timeline or []
        self.replies = replies or []
        self.searches = searches or {}
        self.page_size = page_size
        self.queries: list[str] = []
        self.page_requests: list[tuple[str, str | None, int]] = []

    async def resolve_user(self, username: str):
        return user(username)

    def iter_user_tweet_pages(
        self, user_id: str, *, cursor: str | None = None, limit: int = -1
    ) -> AsyncIterator[CollectorPage]:
        return self._pages(
            self.timeline,
            source="user_tweets",
            operation="UserTweets",
            cursor=cursor,
            limit=limit,
        )

    def iter_user_tweet_and_reply_pages(
        self, user_id: str, *, cursor: str | None = None, limit: int = -1
    ) -> AsyncIterator[CollectorPage]:
        return self._pages(
            self.replies,
            source="user_tweets_and_replies",
            operation="UserTweetsAndReplies",
            cursor=cursor,
            limit=limit,
        )

    def iter_search_pages(
        self, query: str, *, cursor: str | None = None, limit: int = -1
    ) -> AsyncIterator[CollectorPage]:
        self.queries.append(query)
        values: list[Any] = []
        for key, matches in self.searches.items():
            if key in query:
                values = list(matches)
                break
        return self._pages(
            values,
            source="search",
            operation="SearchTimeline",
            cursor=cursor,
            limit=limit,
        )

    async def iter_user_tweets(self, user_id: str, *, limit: int = -1):
        async for page in self.iter_user_tweet_pages(user_id, limit=limit):
            for value in page.items:
                yield value

    async def iter_user_tweets_and_replies(self, user_id: str, *, limit: int = -1):
        async for page in self.iter_user_tweet_and_reply_pages(user_id, limit=limit):
            for value in page.items:
                yield value

    async def iter_search(self, query: str, *, limit: int = -1):
        async for page in self.iter_search_pages(query, limit=limit):
            for value in page.items:
                yield value

    async def _pages(
        self,
        values: list[Any],
        *,
        source: str,
        operation: str,
        cursor: str | None,
        limit: int,
    ) -> AsyncIterator[CollectorPage]:
        self.page_requests.append((source, cursor, limit))
        start = self._cursor_offset(cursor)
        stop = len(values) if limit < 0 else min(len(values), start + limit)
        request_cursor = cursor
        local_index = 0
        offset = start
        while offset < stop:
            chunk = values[offset : min(stop, offset + self.page_size)]
            next_offset = offset + len(chunk)
            next_cursor = f"offset:{next_offset}" if next_offset < len(values) else None
            raw_payload: dict[str, Any] = {"tweets": chunk, "instructions": []}
            if next_cursor is not None:
                raw_payload["instructions"].append(
                    {"cursorType": "Bottom", "value": next_cursor}
                )
            yield CollectorPage(
                source=source,
                operation=operation,
                request_cursor=request_cursor,
                next_cursor=next_cursor,
                items=tuple(chunk),
                raw_payload=raw_payload,
                page_index=local_index,
            )
            request_cursor = next_cursor
            offset = next_offset
            local_index += 1

    @staticmethod
    def _cursor_offset(cursor: str | None) -> int:
        if cursor is None:
            return 0
        prefix = "offset:"
        if not cursor.startswith(prefix):
            raise ValueError(f"invalid fake cursor: {cursor}")
        return int(cursor.removeprefix(prefix))
