from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RawArtifact:
    path: Path
    sha256: str
    size: int


class RawStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def write_json(self, relative: Path, payload: Any) -> RawArtifact:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        compressed = gzip.compress(data, compresslevel=6, mtime=0)
        path.write_bytes(compressed)
        return RawArtifact(path=path, sha256=hashlib.sha256(compressed).hexdigest(), size=len(compressed))
