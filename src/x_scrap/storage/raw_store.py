from __future__ import annotations

import gzip
import hashlib
import json
import os
import uuid
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
        compressed, digest = self._encode(payload)
        return self._write(relative, compressed, digest)

    def write_content_addressed_json(
        self,
        relative_dir: Path,
        payload: Any,
        *,
        prefix: str,
    ) -> RawArtifact:
        """Write immutable evidence without allowing a rejected retry to overwrite it."""

        compressed, digest = self._encode(payload)
        filename = f"{prefix}-{digest[:16]}.json.gz"
        return self._write(relative_dir / filename, compressed, digest)

    @staticmethod
    def _encode(payload: Any) -> tuple[bytes, str]:
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        compressed = gzip.compress(data, compresslevel=6, mtime=0)
        return compressed, hashlib.sha256(compressed).hexdigest()

    def _write(self, relative: Path, compressed: bytes, digest: str) -> RawArtifact:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = path.read_bytes()
            existing_digest = hashlib.sha256(existing).hexdigest()
            if existing_digest != digest:
                raise ValueError(f"raw artifact path already contains different content: {relative}")
            return RawArtifact(path=path, sha256=digest, size=len(existing))

        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(compressed)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return RawArtifact(path=path, sha256=digest, size=len(compressed))
