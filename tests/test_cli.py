from __future__ import annotations

import json

import pytest

import x_scrap.cli as cli
from x_scrap.cli import build_parser


def test_cli_parses_user_export_contract():
    args = build_parser().parse_args(
        ["--home", "state", "user", "export", "--username", "alice", "--no-resume"]
    )
    assert args.username == "alice"
    assert args.no_resume is True


def test_cookie_cannot_be_supplied_in_process_arguments():
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["auth", "add-cookie", "--label", "primary", "--cookie", "auth_token=x; ct0=y"]
        )


def test_cookie_uses_no_echo_prompt_and_is_not_printed(monkeypatch, tmp_path, capsys):
    secret = "auth_token=" + "a" * 32 + "; ct0=" + "b" * 32
    recorded: dict[str, str] = {}

    class FakeAdapter:
        def __init__(self, accounts_db):
            recorded["database"] = str(accounts_db)

        async def add_cookie(self, label: str, cookie_header: str) -> None:
            recorded["label"] = label
            recorded["cookie"] = cookie_header

    monkeypatch.setattr(cli, "TwscrapeAdapter", FakeAdapter)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: secret)

    result = cli.main(
        ["--home", str(tmp_path / "state"), "auth", "add-cookie", "--label", "primary"]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert recorded["cookie"] == secret
    assert secret not in captured.out
    assert secret not in captured.err
    assert json.loads(captured.out)["status"] == "ADDED"


def test_cli_errors_are_redacted_before_stderr(monkeypatch, tmp_path, capsys):
    secret = "c" * 32

    class FakeAdapter:
        def __init__(self, accounts_db):
            pass

        async def list_accounts(self):
            raise RuntimeError(f"Authorization: Bearer {secret}; auth_token={secret}")

    monkeypatch.setattr(cli, "TwscrapeAdapter", FakeAdapter)

    result = cli.main(["--home", str(tmp_path / "state"), "auth", "list"])

    captured = capsys.readouterr()
    assert result == 1
    assert secret not in captured.err
    payload = json.loads(captured.err)
    assert payload["status"] == "ERROR"
    assert "<redacted>" in payload["message"]
