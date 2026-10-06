"""Trial registry (PREREG §0 rules 3 and 5).

Every evaluation is logged with a timestamp, the code hash, and the data
hash. An unlogged evaluation is a protocol breach. The registry is a
JSON-lines file; each record is self-describing so the log stays readable
without the code.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def code_hash(paths: list[str]) -> str:
    """SHA-256 over the concatenated bytes of the given source files."""
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(Path(p).read_bytes())
    return h.hexdigest()


def data_hash(payload: bytes) -> str:
    """SHA-256 of an opaque data descriptor (panel manifest, ledger bytes)."""
    return hashlib.sha256(payload).hexdigest()


class Registry:
    """Append-only JSON-lines trial registry."""

    def __init__(self, path: str | Path):
        self._path = Path(path)

    def log(self, trial_id: str, description: str, code_sha: str,
            data_sha: str, params: dict[str, Any],
            result_summary: dict[str, Any]) -> dict[str, Any]:
        """Append one evaluation record; returns the record."""
        record = {
            "trial_id": trial_id,
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "description": description,
            "code_sha256": code_sha,
            "data_sha256": data_sha,
            "params": params,
            "result_summary": result_summary,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def trials(self) -> list[dict[str, Any]]:
        """All logged records, oldest first."""
        if not self._path.exists():
            return []
        return [json.loads(line) for line in
                self._path.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def has(self, trial_id: str) -> bool:
        return any(t["trial_id"] == trial_id for t in self.trials())
