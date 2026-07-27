from x_scrap.cli import build_parser


def test_cli_parses_user_export_contract():
    args = build_parser().parse_args(
        ["--home", "state", "user", "export", "--username", "alice", "--no-resume"]
    )
    assert args.username == "alice"
    assert args.no_resume is True
