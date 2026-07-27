import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _load_secret_audit():
    path = ROOT / "scripts" / "devflow" / "secret_audit.py"
    spec = importlib.util.spec_from_file_location("secret_audit", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_repository_has_no_high_confidence_secret_material():
    result = _load_secret_audit().audit(ROOT)
    assert result["status"] == "PASS", result


def test_twscrape_telemetry_is_forced_off_before_import():
    source = (ROOT / "src/x_scrap/adapters/twscrape_adapter.py").read_text(encoding="utf-8")
    assert source.index("_disable_upstream_telemetry()") < source.index("from twscrape import API")
    assert 'os.environ["TWS_TELEMETRY"] = "0"' in source
    assert 'os.environ["DO_NOT_TRACK"] = "1"' in source
