"""Trial registry: append-only log of every evaluation (PREREG §0).

Rules 3/5: each evaluation records a timestamp, the code hash, and the
data hash. Rule 5: an unlogged evaluation is a protocol breach.

Two mechanisms enforce this:

- ``logged_run``: a context manager for evaluations. It appends a
  "complete" record on clean exit and a "failed" record (with the
  exception) when the block raises — so breach evidence is preserved,
  not lost.
- ``run_evaluation`` (walkforward.py) requires a registry: the
  walk-forward harness cannot run without logging. Direct
  ``simulate_trade`` calls (unit tests, notebooks) are not evaluations
  under §0 rule 5; the evaluation entry points enforce logging.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def code_hash(paths: list[str | Path]) -> str:
    """SHA-256 over the concatenated bytes of the given files."""
    h = hashlib.sha256()
    for p in sorted(Path(x) for x in paths):
        h.update(p.read_bytes())
    return h.hexdigest()


def data_hash(payload: bytes) -> str:
    """SHA-256 over an opaque data payload."""
    return hashlib.sha256(payload).hexdigest()


class TrialRegistry:
    """Append-only JSON-lines registry of evaluation trials."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, trial_id: str, description: str, code_sha: str,
            data_sha: str, params: dict[str, Any],
            result_summary: dict[str, Any]) -> dict[str, Any]:
        """Append one evaluation record; returns the record."""
        record = {
            "trial_id": trial_id,
            "description": description,
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "code_sha256": code_sha,
            "data_sha256": data_sha,
            "params": params,
            "result_summary": result_summary,
        }
        with self.path.open("a") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    @contextmanager
    def logged_run(self, trial_id: str, description: str, code_sha: str,
                   data_sha: str, params: dict[str, Any]
                   ) -> Iterator[dict[str, Any]]:
        """Run an evaluation with mandatory logging (PREREG §0 rule 5).

        Yields a mutable ``result_summary`` dict. On clean exit appends a
        "complete" record; if the block raises, appends a "failed" record
        (with the exception type and message) and re-raises — the breach
        evidence is preserved either way.
        """
        result_summary: dict[str, Any] = {}
        try:
            yield result_summary
        except Exception as exc:  # noqa: BLE001  (record, then re-raise)
            result_summary["status"] = "failed"
            result_summary["error"] = f"{type(exc).__name__}: {exc}"
            self.log(trial_id, description, code_sha, data_sha, params,
                     result_summary)
            raise
        result_summary.setdefault("status", "complete")
        self.log(trial_id, description, code_sha, data_sha, params,
                 result_summary)

    def code_hash_of_package(self) -> str:
        """SHA-256 over the arcis research package sources."""
        pkg = Path(__file__).resolve().parent
        return code_hash([p for p in pkg.rglob("*.py") if p.is_file()])

    def data_hash_of_panel(self, panel: Any) -> str:
        """SHA-256 over the panel's bars (symbol, date, OHLCV)."""
        h = hashlib.sha256()
        for symbol in panel.symbols:
            for d in sorted(panel.bars_for(symbol)):
                b = panel.bars_for(symbol)[d]
                h.update(f"{symbol}|{d}|{b.open}|{b.high}|{b.low}|"
                         f"{b.close}|{b.volume}\n".encode())
        return h.hexdigest()

    def data_hash_of_candidates(self, candidates: list[Any]) -> str:
        """SHA-256 over the candidate list (all fields that change results)."""
        h = hashlib.sha256()
        for c in candidates:
            h.update(f"{c.symbol}|{c.signal_date}|{c.limit}|{c.stop}|"
                     f"{c.target}|{c.shares}|"
                     f"{sorted(c.earnings_dates)}|{sorted(c.blackouts)}|"
                     f"{sorted(c.events.items())}|{sorted(c.splits.items())}|"
                     f"{sorted(c.exdiv_dates)}\n".encode())
        return h.hexdigest()

    def data_hash_of_halts(self, panel: Any) -> str:
        """SHA-256 over declared halts (symbol, date)."""
        h = hashlib.sha256()
        for symbol in sorted(panel.halts):
            for d in sorted(panel.halts[symbol]):
                h.update(f"{symbol}|{d}\n".encode())
        return h.hexdigest()

    def trials(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in
                self.path.read_text().splitlines() if line.strip()]

    def has(self, trial_id: str) -> bool:
        return any(t["trial_id"] == trial_id for t in self.trials())
