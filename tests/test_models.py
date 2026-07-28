from datetime import UTC, datetime

from fakes import post, user

from x_scrap.domain.models import PostRecord, UserSnapshot

UTC = UTC


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


def test_user_snapshot_round_trip_preserves_canonical_fields_without_raw_nesting():
    captured = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    original = UserSnapshot(
        user_id="7",
        username="alice",
        display_name="Alice",
        created_at=datetime(2020, 2, 3, tzinfo=UTC),
        protected=False,
        followers_count=42,
        statuses_count=99,
        profile_url="https://x.com/alice",
        description="profile",
        captured_at=captured,
        raw={"id_str": "7", "screen_name": "alice"},
    )

    restored = UserSnapshot.from_object(original.to_dict())

    assert restored == original
    assert restored.raw == {"id_str": "7", "screen_name": "alice"}
