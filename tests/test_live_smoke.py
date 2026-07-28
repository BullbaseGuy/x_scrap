from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "live" / "run_user_export_smoke.py"
spec = importlib.util.spec_from_file_location("run_user_export_smoke", SCRIPT)
smoke = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(smoke)


def test_live_smoke_refuses_ci(monkeypatch):
    monkeypatch.setenv("CI", "true")
    with pytest.raises(SystemExit, match="forbidden in CI"):
        smoke.run(["alice", "--acknowledge-live-x"])


def test_live_smoke_requires_explicit_acknowledgement(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(SystemExit, match="acknowledge-live-x"):
        smoke.run(["alice"])


def test_live_smoke_preflight_and_live_commands_never_accept_cookie_arguments(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    calls: list[list[str]] = []
    monkeypatch.setattr(smoke, "main", lambda argv: calls.append(list(argv)) or 0)

    assert smoke.run(["--home", "state", "--preflight-only"]) == 0
    assert calls[-1] == ["--home", "state", "auth", "list"]

    assert (
        smoke.run(
            [
                "alice",
                "--home",
                "state",
                "--acknowledge-live-x",
                "--start",
                "2026-01-01T00:00:00Z",
                "--cutoff",
                "2026-01-02T00:00:00Z",
            ]
        )
        == 0
    )
    command = calls[-1]
    assert command[:6] == ["--home", "state", "user", "export", "--username", "alice"]
    assert "--cookie" not in command
    assert "auth_token" not in " ".join(command)
