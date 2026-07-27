from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_workflows_use_current_official_actions_and_read_only_permissions():
    files = list(WORKFLOWS.glob("*.yml"))
    assert files
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert "pull_request_target" not in source
        assert "actions/checkout@v7" in source
        assert "actions/setup-python@v7" in source
        assert "permissions:\n  contents: read" in source
        assert "persist-credentials: false" in source


def test_live_authenticated_scripts_are_not_invoked_by_ci():
    for path in WORKFLOWS.glob("*.yml"):
        source = path.read_text(encoding="utf-8")
        assert "scripts/live/" not in source
        assert "run_user_export_smoke.py" not in source
        assert "run_e2e_case.py" not in source
