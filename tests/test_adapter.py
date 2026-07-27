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
        if name == "twscrape":
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

    fake_module = types.ModuleType("twscrape")
    fake_module.API = FakeAPI
    monkeypatch.setitem(sys.modules, "twscrape", fake_module)
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
