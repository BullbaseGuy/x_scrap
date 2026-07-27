from datetime import datetime, timezone

from fakes import post, user
from x_scrap.domain.models import PostRecord, UserSnapshot

UTC = timezone.utc


def test_normalizes_ids_as_strings_and_relations():
    value = post(
        123,
        datetime(2026, 1, 1, tzinfo=UTC),
        inReplyToTweetId=100,
        quotedTweet={"id": 99},
    )
    record = PostRecord.from_object(value, source="test")
    assert record.post_id == "123"
    assert record.in_reply_to_post_id == "100"
    assert record.quoted_post_id == "99"
    assert record.is_reply and record.is_quote


def test_user_snapshot_preserves_created_time():
    created = datetime(2020, 2, 3, tzinfo=UTC)
    snapshot = UserSnapshot.from_object(user(created=created))
    assert snapshot.created_at == created
    assert snapshot.user_id == "7"
