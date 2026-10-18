"""Extend the immutable v2 store with independently snapshotted v3 sources."""
from pathlib import Path

from research.accuracy_v2.storage import (ROOT, Store as BaseStore, atomic_bytes, digest,
    environment_identity, exclusive, read_checked, sha, utc, write_checked)
from . import VERSION


def extension_identity():
    return {"schema": VERSION, "sources": {str(p.relative_to(ROOT)): sha(p)
            for p in sorted((ROOT / "research/accuracy_v3").glob("*.py"))}}


class Store(BaseStore):
    def __init__(self, directory, identity, resume=False):
        if identity["extension"] != extension_identity():
            raise ValueError("V3 source identity changed; use the recorded code or a fresh run")
        super().__init__(directory, identity, resume)
        for relative, expected in identity["extension"]["sources"].items():
            path = self.path / "source_snapshot" / relative
            if not resume:
                atomic_bytes(path, (ROOT / relative).read_bytes())
            if not path.is_file() or sha(path) != expected:
                raise ValueError(f"V3 source snapshot corrupted: {relative}")

    def seal(self, query_ids, validate):
        if self.identity["extension"] != extension_identity():
            raise ValueError("V3 source changed during execution")
        super().seal(query_ids, validate)
        path = self.path / "manifest.json"
        manifest = read_checked(path)
        manifest["schema"] = VERSION
        write_checked(path, manifest)

    def verify(self):
        if self.identity["extension"] != extension_identity():
            raise ValueError("V3 source changed since collection")
        return super().verify()
