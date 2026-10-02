"""Article versioning: tamper-evident version hashes and the per-symbol index.

The version hash is sha256 over the canonical JSON of the raw article,
excluding EXCLUDED_FIELDS. The T1 preflight compared two identical live
responses and found no volatile article fields, so EXCLUDED_FIELDS is
intentionally empty. If Alpaca ever adds volatile fields (e.g. a
per-fetch nonce), add them here — never silently.

Index layout: data_root/index/<symbol>.jsonl, one {"id", "version_hash"}
entry per article, appended in arrival order, deduplicated by article id.

rebuild() replays every article JSONL and rewrites every index file from
scratch. It fails if any recomputed hash differs from the indexed one.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from arcis.recorder.errors import StorageLayoutError
from arcis.recorder.store import SYMBOL_PATTERN, canonical_json

EXCLUDED_FIELDS: frozenset[str] = frozenset()


def version_hash(raw: dict[str, Any]) -> str:
    """sha256 over the canonical JSON of the raw article minus excluded fields."""
    filtered = {k: v for k, v in raw.items() if k not in EXCLUDED_FIELDS}
    return hashlib.sha256(canonical_json(filtered).encode("utf-8")).hexdigest()


class VersionIndex:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root.resolve()
        self.index_dir = self.data_root / "index"
        self._known_ids: dict[str, set[int]] = {}

    def _index_path(self, symbol: str) -> Path:
        if not SYMBOL_PATTERN.fullmatch(symbol):
            raise StorageLayoutError(f"invalid symbol for index: {symbol!r}")
        path = (self.index_dir / f"{symbol}.jsonl").resolve()
        if self.data_root not in path.parents:
            raise StorageLayoutError(f"path escapes data root: {path}")
        return path

    def _load_ids(self, symbol: str) -> set[int]:
        if symbol not in self._known_ids:
            ids: set[int] = set()
            path = self._index_path(symbol)
            if path.is_file():
                with path.open() as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            ids.add(json.loads(line)["id"])
            self._known_ids[symbol] = ids
        return self._known_ids[symbol]

    def append(self, symbol: str, article_id: int, vhash: str) -> bool:
        """Index id -> vhash unless already indexed. Returns True if appended."""
        if article_id in self._load_ids(symbol):
            return False
        path = self._index_path(symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(canonical_json({"id": article_id, "version_hash": vhash}) + "\n")
        self._known_ids[symbol].add(article_id)
        return True

    def lookup(self, symbol: str, article_id: int) -> str | None:
        """Return the indexed hash for the article, or None if not indexed."""
        path = self._index_path(symbol)
        if not path.is_file():
            return None
        with path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    entry = json.loads(line)
                    if entry["id"] == article_id:
                        result: str | None = entry["version_hash"]
                        return result
        return None

    def rebuild(self) -> list[str]:
        """Replay every article JSONL, rewrite every index from scratch.
        Returns error strings; a recomputed hash that differs from the
        indexed one is reported (tamper-evident)."""
        errors: list[str] = []
        articles_dir = self.data_root / "articles"
        if not articles_dir.is_dir():
            return errors
        for symbol_dir in sorted(articles_dir.iterdir()):
            if not symbol_dir.is_dir():
                continue
            symbol = symbol_dir.name
            if not SYMBOL_PATTERN.fullmatch(symbol):
                continue
            entries: list[tuple[int, str]] = []
            seen: set[int] = set()
            for jsonl in sorted(symbol_dir.glob("*.jsonl")):
                with jsonl.open() as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        raw = json.loads(line)
                        article_id = raw["id"]
                        vhash = version_hash(raw)
                        indexed = self.lookup(symbol, article_id)
                        if indexed is not None and indexed != vhash:
                            errors.append(
                                f"{symbol}:{article_id}: version hash mismatch "
                                "(article changed since indexing)"
                            )
                        if article_id not in seen:
                            seen.add(article_id)
                            entries.append((article_id, vhash))
            self._write_index(symbol, entries)
            self._known_ids[symbol] = {aid for aid, _ in entries}
        return errors

    def _write_index(self, symbol: str, entries: list[tuple[int, str]]) -> None:
        path = self._index_path(symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w") as f:
            for article_id, vhash in entries:
                f.write(canonical_json({"id": article_id, "version_hash": vhash}) + "\n")
        os.rename(tmp, path)
