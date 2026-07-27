from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime

import pytest

from x_scrap.config import AppPaths
from x_scrap.export.writer import write_export
from x_scrap.security import REDACTED, redact_text, redact_value
from x_scrap.storage.database import Database
from x_scrap.storage.page_repository import PageRepository
from x_scrap.storage.raw_store import RawStore


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_redaction_covers_cookie_headers_authorization_and_url_queries():
    secret_a = "a" * 32
    secret_b = "b" * 32
    value = (
        f"Cookie: auth_token={secret_a}; ct0={secret_b}\n"
        f"Authorization: Bearer {secret_a}\n"
        f"https://example.invalid/path?ct0={secret_b}&safe=1#auth_token={secret_a}"
    )
    redacted = redact_text(value)
    assert secret_a not in redacted
    assert secret_b not in redacted
    assert redacted.count(REDACTED) >= 3


def test_recursive_redaction_uses_sensitive_keys_and_strings():
    secret = "s" * 32
    value = {
        "headers": {"Authorization": f"Bearer {secret}", "Cookie": f"ct0={secret}"},
        "auth_token": secret,
        "messages": [f"access_token={secret}", "safe"],
    }
    redacted = redact_value(value)
    assert secret not in json.dumps(redacted)
    assert redacted["auth_token"] == REDACTED
    assert redacted["headers"]["Authorization"] == REDACTED


def test_state_home_inside_git_worktree_is_rejected(tmp_path):
    repository = tmp_path / "repo"
    (repository / ".git").mkdir(parents=True)
    with pytest.raises(ValueError, match="outside a Git worktree"):
        AppPaths.discover(repository / "state").ensure()


def test_private_modes_apply_to_state_databases_raw_and_exports(tmp_path):
    paths = AppPaths.discover(tmp_path / "state").ensure()
    database = Database(paths.jobs_db)
    database.create_job(
        username="alice",
        cutoff_at=datetime(2026, 1, 2, tzinfo=UTC),
        scope="authored",
        output_dir=paths.exports / "alice" / "job",
    )
    raw = RawStore(paths.raw)
    artifact = raw.write_json(tmp_path.relative_to(tmp_path) / "job" / "page.json.gz", {"ok": True})
    output = paths.exports / "alice" / "job"
    write_export(
        output,
        manifest={
            "job_id": "job",
            "username": "alice",
            "post_count": 0,
            "start_at": "2026-01-01T00:00:00Z",
            "cutoff_at": "2026-01-02T00:00:00Z",
        },
        profile={"username": "alice"},
        coverage={"status": "COMPLETE_PUBLICLY_RETRIEVABLE"},
        posts=[],
    )

    if os.name == "posix":
        assert _mode(paths.home) == 0o700
        assert _mode(paths.raw) == 0o700
        assert _mode(paths.exports) == 0o700
        assert _mode(paths.jobs_db) == 0o600
        assert _mode(artifact.path) == 0o600
        assert _mode(output) == 0o700
        for path in output.iterdir():
            assert _mode(path) == 0o600


def test_persisted_errors_and_events_are_redacted(tmp_path):
    secret = "z" * 32
    database = Database(tmp_path / "jobs.db")
    job_id = database.create_job(
        username="alice",
        cutoff_at=datetime(2026, 1, 2, tzinfo=UTC),
        scope="authored",
        output_dir=tmp_path / "out",
    )
    database.update_job(
        job_id,
        error_code="AUTH",
        error_message=f"auth_token={secret}; ct0={secret}",
    )
    database.add_event(
        job_id,
        "ERROR",
        {"headers": {"Authorization": f"Bearer {secret}"}, "url": f"https://x/?ct0={secret}"},
    )
    pages = PageRepository(database)
    pages.ensure_scope(job_id, "timeline:user", "user_tweets")
    pages.fail_scope(job_id, "timeline:user", f"Cookie: auth_token={secret}; ct0={secret}")

    assert secret not in json.dumps(database.get_job(job_id))
    assert secret not in json.dumps(pages.get_scope(job_id, "timeline:user"))
    with database.connect() as connection:
        event = connection.execute(
            "SELECT details FROM events WHERE job_id=? ORDER BY event_id DESC LIMIT 1",
            (job_id,),
        ).fetchone()
    assert event is not None
    assert secret not in event["details"]
