import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_active_task_state_and_required_documents_are_consistent(monkeypatch):
    scripts = ROOT / "scripts" / "devflow"
    monkeypatch.syspath_prepend(str(scripts))
    validate_state = _load("validate_state", scripts / "validate_state.py")
    result = validate_state.validate_active_tasks(ROOT)
    assert result["status"] == "PASS", result


def test_agent_execution_is_disabled():
    import json

    config = json.loads((ROOT / ".devflow/project.json").read_text(encoding="utf-8"))
    policy = json.loads((ROOT / ".devflow/codex-entrypoints.yaml").read_text(encoding="utf-8"))
    assert config["features"]["agent_execution"] == "disabled"
    assert config["features"]["automatic_merge"] is False
    assert policy["policy"] == "disabled"
    assert policy["codex_calls"] == 0
