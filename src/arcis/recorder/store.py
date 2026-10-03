"""Append-only article store.

Layout:
    data_root/articles/<symbol>/<YYYY-MM-DD>.jsonl
    data_root/articles/<symbol>/<YYYY-MM-DD>.manifest.json

Each JSONL line is the raw article JSON exactly as the API returned it
(no enrichment), appended in arrival order. Articles are deduplicated by
(symbol, id). The manifest is recomputed and written atomically (temp file
+ rename) after the JSONL is closed.

verify() re-reads every JSONL, recomputes its manifest, and reports any
mismatch, duplicate (symbol, id), or out-of-order created_at.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from arcis.recorder.client import FetchedArticle
from arcis.recorder.errors import StorageLayoutError, StoreError

SYMBOL_PATTERN = re.compile(r"[A-Z0-9.\-^]{1,12}")
MANIFEST_SUFFIX = ".manifest.json"


def parse_day(created_at: str) -> date:
    """Extract the calendar date from an ISO-8601 created_at string."""
    try:
        return datetime.fromisoformat(created_at.replace("Z", "+00:00")).date()
    except ValueError as e:
        raise StoreError(f"unparseable created_at {created_at!r}: {e}") from e


def canonical_json(obj: dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


class NewsStore:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root.resolve()
        self.articles_dir = self.data_root / "articles"

    def _check_symbol(self, symbol: str) -> None:
        if not SYMBOL_PATTERN.fullmatch(symbol):
            raise StorageLayoutError(f"invalid symbol for storage: {symbol!r}")

    def _article_path(self, symbol: str, day: date) -> Path:
        self._check_symbol(symbol)
        path = (self.articles_dir / symbol / f"{day.isoformat()}.jsonl").resolve()
        if self.data_root not in path.parents:
            raise StorageLayoutError(f"path escapes data root: {path}")
        return path

    def _manifest_path(self, article_path: Path) -> Path:
        return article_path.with_name(article_path.name + MANIFEST_SUFFIX)

    def _read_ids(self, path: Path) -> tuple[list[int], str | None]:
        """Existing article ids and the last created_at in the file."""
        ids: list[int] = []
        last_created: str | None = None
        if not path.is_file():
            return ids, last_created
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                ids.append(obj["id"])
                last_created = obj["created_at"]
        return ids, last_created

    def append(self, symbol: str, fetched: FetchedArticle) -> bool:
        """Append the article unless (symbol, id) is already stored.
        Returns True when the article was appended. Out-of-order articles
        (older than the last stored) are skipped, not stored — the 24h poll
        window overlaps previously stored data by design."""
        day = parse_day(fetched.article.created_at)
        path = self._article_path(symbol, day)
        existing_ids, last_created = self._read_ids(path)
        if fetched.article.id in existing_ids:
            return False
        if last_created is not None and fetched.article.created_at < last_created:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(canonical_json(fetched.raw) + "\n")
        self._write_manifest(path)
        return True

    def _manifest_for(self, path: Path) -> dict[str, Any]:
        raw = path.read_bytes()
        records = []
        with path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "records": len(records),
            "first_created_at": records[0].get("created_at") if records else None,
            "last_created_at": records[-1].get("created_at") if records else None,
            "article_ids": [r.get("id") for r in records],
        }

    def _write_manifest(self, path: Path) -> None:
        manifest = self._manifest_for(path)
        target = self._manifest_path(path)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        os.rename(tmp, target)

    def verify(self) -> list[str]:
        """Re-read every JSONL and check it against its manifest, plus
        duplicate and ordering invariants. Returns error strings."""
        errors: list[str] = []
        if not self.articles_dir.is_dir():
            return errors
        for path in sorted(self.articles_dir.rglob("*.jsonl")):
            errors.extend(self._verify_file(path))
        return errors

    def _verify_file(self, path: Path) -> list[str]:
        errors: list[str] = []
        manifest_path = self._manifest_path(path)
        if not manifest_path.is_file():
            return [f"{path}: missing manifest"]
        try:
            expected = json.loads(manifest_path.read_text())
        except ValueError as e:
            return [f"{path}: manifest is not valid JSON: {e}"]
        actual = self._manifest_for(path)
        manifest_keys = (
            "sha256",
            "bytes",
            "records",
            "first_created_at",
            "last_created_at",
            "article_ids",
        )
        for key in manifest_keys:
            if actual[key] != expected.get(key):
                errors.append(f"{path}: manifest mismatch on {key}")
        seen: set[int] = set()
        last_created: str | None = None
        with path.open() as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    errors.append(f"{path}:{i}: not valid JSON")
                    continue
                article_id = obj.get("id")
                if article_id in seen:
                    errors.append(f"{path}:{i}: duplicate article id {article_id}")
                seen.add(article_id)
                created = obj.get("created_at", "")
                if last_created is not None and created < last_created:
                    errors.append(f"{path}:{i}: out-of-order created_at")
                last_created = created
        return errors
