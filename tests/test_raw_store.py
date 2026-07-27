from __future__ import annotations

import gzip
import json

import pytest

from x_scrap.storage.raw_store import RawStore


def test_content_addressed_raw_artifacts_are_immutable_and_deterministic(tmp_path):
    store = RawStore(tmp_path / "raw")
    payload = {"page": 1, "items": [{"id": "1"}]}

    first = store.write_content_addressed_json(
        tmp_path.relative_to(tmp_path) / "job" / "pages",
        payload,
        prefix="page-000000",
    )
    second = store.write_content_addressed_json(
        tmp_path.relative_to(tmp_path) / "job" / "pages",
        payload,
        prefix="page-000000",
    )

    assert first == second
    assert first.path.name.startswith("page-000000-")
    assert json.loads(gzip.decompress(first.path.read_bytes())) == payload
    assert not list(first.path.parent.glob("*.tmp"))


def test_fixed_raw_path_refuses_different_content(tmp_path):
    store = RawStore(tmp_path / "raw")
    relative = tmp_path.relative_to(tmp_path) / "job" / "fixed.json.gz"
    store.write_json(relative, {"value": 1})

    with pytest.raises(ValueError, match="different content"):
        store.write_json(relative, {"value": 2})
