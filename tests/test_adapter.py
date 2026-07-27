from __future__ import annotations

import builtins
import importlib
import os
import sys
import types
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import x_scrap.adapters.twscrape_adapter as adapter_module
from x_scrap.adapters.base import AuthRequired, RateLimited, TransientUpstreamError, UpstreamChanged


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def _install_fake_twscrape(monkeypatch, api_class, parser=None):
    package = types.ModuleType("twscrape")
    package.API = api_class
    models = types.ModuleType("twscrape.models")
    models.parse_tweets = parser or (lambda payload, limit: payload.get("tweets", []))
    monkeypatch.setitem(sys.modules, "twscrape", package)
    monkeypatch.setitem(sys.modules, "twscrape.models", models)


@pytest.mark.parametrize(
    "value",
    [
        "auth_token=x",
        "ct0=y",
        "auth_token=; ct0=y",
        "auth_token=x; ct0=",
        "not_auth_token=x; ct0=y",
        "auth_token=x\nct0=y",
    ],
)
def test_cookie_validation_rejects_missing_empty_or_multiline_fields(value):
    with pytest.raises(ValueError):
        adapter_module._validate_cookie(value)


def test_cookie_validation_accepts_exact_non_empty_fields():
    adapter_module._validate_cookie("other=1; auth_token=x; ct0=y")


def test_module_reload_does_not_eagerly_import_twscrape(monkeypatch):
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "twscrape":
            raise AssertionError("twscrape was imported at module import time")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    importlib.reload(adapter_module)


def test_missing_twscrape_dependency_has_actionable_error(monkeypatch, tmp_path):
    original_import = builtins.__import__

    def missing_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "twscrape" or name.startswith("twscrape."):
            raise ImportError("synthetic missing dependency")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", missing_import)
    with pytest.raises(RuntimeError, match="twscrape is not installed"):
        adapter_module.TwscrapeAdapter(tmp_path / "accounts.db")


@pytest.mark.asyncio
async def test_adapter_forces_telemetry_off_and_redacts_account_errors(monkeypatch, tmp_path):
    class FakePool:
        def __init__(self):
            self.added: tuple[str, str] | None = None

        async def add_account_cookies(self, label: str, cookie_header: str) -> None:
            self.added = (label, cookie_header)

        async def get_all(self):
            return [
                SimpleNamespace(
                    username="primary",
                    active=True,
                    last_used=None,
                    error_msg="failed auth_token=secret; ct0=csrf",
                )
            ]

    class FakeAPI:
        def __init__(self, accounts_db: str, *, proxy: str | None = None):
            assert accounts_db.endswith("accounts.db")
            assert proxy is None
            assert os.environ["TWS_TELEMETRY"] == "0"
            assert os.environ["DO_NOT_TRACK"] == "1"
            self.pool = FakePool()

    _install_fake_twscrape(monkeypatch, FakeAPI)
    monkeypatch.setenv("TWS_TELEMETRY", "1")
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)

    adapter = adapter_module.TwscrapeAdapter(tmp_path / "accounts.db")
    await adapter.add_cookie(" primary ", "auth_token=x; ct0=y")
    assert adapter._api.pool.added == ("primary", "auth_token=x; ct0=y")

    accounts = await adapter.list_accounts()
    assert accounts == [
        {
            "username": "primary",
            "active": True,
            "last_used": None,
            "error_msg": "failed auth_token=<redacted>; ct0=<redacted>",
        }
    ]
    assert set(accounts[0]) == {"username", "active", "last_used", "error_msg"}


@pytest.mark.asyncio
async def test_raw_page_adapter_preserves_cursors_payloads_and_items(monkeypatch, tmp_path):
    class FakeAPI:
        def __init__(self, accounts_db: str, *, proxy: str | None = None):
            self.pool = SimpleNamespace()

        async def user_tweets_raw(self, user_id: int, *, limit: int, kv):
            assert user_id == 7
            assert limit == -1
            assert kv == {"cursor": "resume"}
            yield FakeResponse(
                {
                    "tweets": [{"id": "1"}],
                    "instructions": [{"cursorType": "Bottom", "value": "next-1"}],
                }
            )
            yield FakeResponse({"tweets": [{"id": "2"}], "instructions": []})

    _install_fake_twscrape(monkeypatch, FakeAPI)
    adapter = adapter_module.TwscrapeAdapter(tmp_path / "accounts.db")

    pages = [
        page
        async for page in adapter.iter_user_tweet_pages("7", cursor="resume", limit=-1)
    ]

    assert [page.page_index for page in pages] == [0, 1]
    assert [page.request_cursor for page in pages] == ["resume", "next-1"]
    assert [page.next_cursor for page in pages] == ["next-1", None]
    assert [page.items[0]["id"] for page in pages] == ["1", "2"]
    assert pages[0].artifact_payload()["raw_payload"]["tweets"][0]["id"] == "1"


@pytest.mark.asyncio
async def test_raw_page_adapter_rejects_repeated_cursor(monkeypatch, tmp_path):
    class FakeAPI:
        def __init__(self, accounts_db: str, *, proxy: str | None = None):
            self.pool = SimpleNamespace()

        async def search_raw(self, query: str, *, limit: int, kv):
            yield FakeResponse(
                {
                    "tweets": [{"id": "1"}],
                    "instructions": [{"cursorType": "Bottom", "value": "resume"}],
                }
            )

    _install_fake_twscrape(monkeypatch, FakeAPI)
    adapter = adapter_module.TwscrapeAdapter(tmp_path / "accounts.db")

    with pytest.raises(UpstreamChanged, match="repeated pagination cursor"):
        async for _ in adapter.iter_search_pages("from:alice", cursor="resume"):
            pass


def test_upstream_errors_are_classified_and_redacted_conservatively():
    class SyntheticRateError(RuntimeError):
        reset_at = 1_800_000_000

    rate = adapter_module._classify(SyntheticRateError("429 rate limit"))
    assert isinstance(rate, RateLimited)
    assert rate.reset_at == datetime.fromtimestamp(1_800_000_000, UTC)

    auth = adapter_module._classify(RuntimeError("login challenge auth_token=secret; ct0=csrf"))
    assert isinstance(auth, AuthRequired)
    assert "secret" not in str(auth) and "csrf" not in str(auth)

    assert isinstance(adapter_module._classify(type("NoAccountError", (RuntimeError,), {})()), AuthRequired)
    assert isinstance(
        adapter_module._classify(RuntimeError("GraphQL operation missing 404")), UpstreamChanged
    )
    assert isinstance(
        adapter_module._classify(RuntimeError("503 temporary connection failure")),
        TransientUpstreamError,
    )
    assert isinstance(adapter_module._classify(RuntimeError("unexpected response")), UpstreamChanged)
