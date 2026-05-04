"""LLM-scoring corpus data model + reader for Stage 1 walk-forward (#96.1).

Pre-registration addendum 1 §A3 (`docs/research/pre-registration-stage1-addendum-1.md`)
commits Stage 1 to a pre-computed LLM-scoring corpus rather than live LLM
calls inside the walk-forward loop. This module defines the binding
storage contract.

Why pre-computed (operator's option C choice + reasoning):
- Reproducibility — corpus is SHA-pinned, byte-identical reruns
- Iteration speed — backtester edits don't re-pay LLM inference cost
- Deterministic-ranker shadow comparison — same row filter on same corpus

Storage layout::

    data/corpus/<corpus_id>/
        manifest.json       # per-corpus reproducibility receipts (CorpusManifest)
        entries.jsonl       # one CorpusEntry per line

JSONL is preferred for entries because (a) cheap append at generation time,
(b) stream-read avoids loading 100K+ entries into memory, (c) git-diff-able.

Called by: src/evaluation/backtester.py (#96.4), src/evaluation/walkforward.py (#96.5)
Calls: none
Owns tables: none
Config keys: none
Tests: tests/evaluation/test_corpus.py

The CorpusEntry fields map 1:1 to addendum §A3.1 per-decision artifact
requirements; the CorpusManifest fields map 1:1 to addendum §A3.2 reproducibility
receipts. Drift between this contract and the addendum requires a new addendum.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

# Canonical llm_action values mirror src/attribution/logger.py::_CANONICAL_LLM_ACTIONS
# Duplicated here intentionally to keep this module dependency-free at import.
# Drift between the two is caught by tests/evaluation/test_corpus.py.
_CANONICAL_ACTIONS = frozenset({
    "taken",
    "rejected",
    "parse_failed",
    "conviction_none",
})

# Pre-reg addendum §A1.4 — admissibility requires parse-failure rate ≤ 5%.
# Higher = LLM-pipeline contamination per §7 anti-success diagnostic.
_PARSE_FAILURE_RATE_CEILING = 0.05


@dataclass(frozen=True)
class CorpusEntry:
    """One walk-forward decision point's LLM scoring + provenance.

    Fields map to pre-reg addendum 1 §A3.1 ("per-decision artifact
    requirements"). Field count + names are part of the binding corpus
    contract — adding/removing requires a pre-reg amendment.

    All string fields are required (cannot be None) except where noted.
    """

    # Identity (addendum §A3.1, lines 1-3)
    as_of: str  # ISO ``YYYY-MM-DD`` — the trade decision date
    ticker: str
    model_version: str  # e.g. ``arcis:v1.0.0`` — pre-reg §A1.1 binds to one

    # Prompt provenance (addendum §A3.1, line 4)
    prompt_sha256: str  # 64-char hex SHA256 of the assembled 11-section prompt

    # LLM output (addendum §A3.1, lines 5-7)
    response: str  # raw LLM response string
    llm_action: str  # canonical per src/attribution/logger.py
    llm_conviction: int  # 1-10 INTEGER per src/llm/packet_writer.py clamp

    # Parse provenance (addendum §A3.1, lines 8-9 + #850)
    parse_failed: int  # 0/1 — 1 means conviction came from packet_writer fallback
    parser_strategy_succeeded: str | None  # which of 6 conviction-parse strategies fired

    # Section status (addendum §A3.1, lines 10-11)
    prompt_section_omitted: tuple[int, ...] = field(default_factory=tuple)
    enrichment_pit_warnings: tuple[str, ...] = field(default_factory=tuple)

    # Generation metadata (addendum §A3.1 — implicit but useful for debugging)
    generated_at: str = ""  # ISO datetime when this entry was written

    def __post_init__(self) -> None:
        """Validate canonical-action + range invariants at construction time."""
        if self.llm_action not in _CANONICAL_ACTIONS:
            raise ValueError(
                f"llm_action={self.llm_action!r} is not canonical. "
                f"Allowed: {sorted(_CANONICAL_ACTIONS)}"
            )
        if not (1 <= self.llm_conviction <= 10):
            raise ValueError(
                f"llm_conviction={self.llm_conviction} outside 1-10 range "
                f"(per src/llm/packet_writer.py clamp)"
            )
        if self.parse_failed not in (0, 1):
            raise ValueError(
                f"parse_failed={self.parse_failed} must be 0 or 1"
            )
        if len(self.prompt_sha256) != 64:
            raise ValueError(
                f"prompt_sha256 must be a 64-char hex digest, "
                f"got {len(self.prompt_sha256)} chars"
            )

    def to_json_line(self) -> str:
        """Serialize this entry as a single JSONL line.

        Tuples are converted to lists so json.dumps doesn't choke. The
        fixed-order keys produced by dataclass + asdict ensure the output
        is deterministic (a given (as_of, ticker, model_version) always
        produces a byte-identical line, modulo response/conviction).
        """
        d = asdict(self)
        # asdict converts tuples → lists already; explicit for clarity
        d["prompt_section_omitted"] = list(d["prompt_section_omitted"])
        d["enrichment_pit_warnings"] = list(d["enrichment_pit_warnings"])
        return json.dumps(d, sort_keys=False, ensure_ascii=False)

    @classmethod
    def from_json_line(cls, line: str) -> "CorpusEntry":
        """Parse a single JSONL line into a CorpusEntry."""
        d = json.loads(line)
        return cls(
            as_of=d["as_of"],
            ticker=d["ticker"],
            model_version=d["model_version"],
            prompt_sha256=d["prompt_sha256"],
            response=d["response"],
            llm_action=d["llm_action"],
            llm_conviction=int(d["llm_conviction"]),
            parse_failed=int(d["parse_failed"]),
            parser_strategy_succeeded=d.get("parser_strategy_succeeded"),
            prompt_section_omitted=tuple(d.get("prompt_section_omitted", [])),
            enrichment_pit_warnings=tuple(d.get("enrichment_pit_warnings", [])),
            generated_at=d.get("generated_at", ""),
        )


@dataclass(frozen=True)
class CorpusManifest:
    """Per-corpus reproducibility receipts (addendum 1 §A3.2).

    Stored as ``data/corpus/<corpus_id>/manifest.json``. Required reading
    before consuming a corpus — a manifest with admissibility=='FAIL'
    blocks Stage 1 backtest execution per §A3 corpus contract.
    """

    corpus_id: str  # uuid4 hex
    generated_at: str  # ISO datetime
    code_sha: str  # git SHA at generation time
    model_version: str  # pre-reg §A1.1 binding
    walkforward_window_start: str  # ISO date
    walkforward_window_end: str  # ISO date
    total_decision_points: int
    parse_failure_count: int
    parse_failure_rate: float  # parse_failure_count / total_decision_points
    section_pit_status: dict[int, str]  # {1: "clean", 4: "fixed", 8: "placeholder", ...}
    coverage_limit_hits: dict[str, int]  # {"section_5_insiders": 5, "section_6_news": 0}
    admissibility: str  # "PASS" or "FAIL: <reason>"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "CorpusManifest":
        d = json.loads(text)
        return cls(
            corpus_id=d["corpus_id"],
            generated_at=d["generated_at"],
            code_sha=d["code_sha"],
            model_version=d["model_version"],
            walkforward_window_start=d["walkforward_window_start"],
            walkforward_window_end=d["walkforward_window_end"],
            total_decision_points=int(d["total_decision_points"]),
            parse_failure_count=int(d["parse_failure_count"]),
            parse_failure_rate=float(d["parse_failure_rate"]),
            # JSON serializes int keys as strings — restore int keys
            section_pit_status={int(k): v for k, v in d["section_pit_status"].items()},
            coverage_limit_hits=dict(d["coverage_limit_hits"]),
            admissibility=d["admissibility"],
        )

    def is_admissible(self) -> bool:
        """Whether this corpus may be consumed by Stage 1 backtester."""
        return self.admissibility == "PASS"


def compute_admissibility(
    parse_failure_rate: float,
    section_pit_status: dict[int, str],
) -> str:
    """Decide PASS / FAIL given corpus stats per pre-reg §A1.4 + §A3.

    Rules:
    - parse_failure_rate > 5% (§A1.4 anti-success trigger) → FAIL
    - any required section in section_pit_status with value 'broken' → FAIL
    - all other states (clean/fixed/placeholder/accepted-stale) → PASS
    """
    if parse_failure_rate > _PARSE_FAILURE_RATE_CEILING:
        return (
            f"FAIL: parse_failure_rate={parse_failure_rate:.4f} exceeds "
            f"§A1.4 ceiling of {_PARSE_FAILURE_RATE_CEILING:.2f}"
        )
    broken_sections = sorted(
        n for n, status in section_pit_status.items() if status == "broken"
    )
    if broken_sections:
        return (
            f"FAIL: PIT-broken sections in corpus: {broken_sections}. "
            f"All §A2.1 must-fix trackers must close before corpus generation."
        )
    return "PASS"


def corpus_root() -> Path:
    """Repo-relative root for corpus storage. Override via env in tests."""
    import os

    return Path(os.environ.get("ARCIS_CORPUS_ROOT", "data/corpus"))


def corpus_dir(corpus_id: str) -> Path:
    """Path to the directory holding ``manifest.json`` + ``entries.jsonl``."""
    return corpus_root() / corpus_id


def write_corpus(
    corpus_id: str,
    entries: Iterable[CorpusEntry],
    manifest: CorpusManifest,
) -> Path:
    """Write a fully-formed corpus to disk.

    Single-shot writer — preferred for testing + small corpora. Production
    corpus generation uses streaming append (see #96.3 generator).
    """
    root = corpus_dir(corpus_id)
    root.mkdir(parents=True, exist_ok=True)
    entries_path = root / "entries.jsonl"
    with entries_path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(entry.to_json_line() + "\n")
    manifest_path = root / "manifest.json"
    manifest_path.write_text(manifest.to_json(), encoding="utf-8")
    return root


def load_manifest(corpus_id: str) -> CorpusManifest:
    """Load the manifest for a corpus_id. Raises FileNotFoundError if absent."""
    path = corpus_dir(corpus_id) / "manifest.json"
    return CorpusManifest.from_json(path.read_text(encoding="utf-8"))


def iter_entries(corpus_id: str) -> Iterator[CorpusEntry]:
    """Stream-read entries.jsonl for a corpus_id.

    Use this in the backtester / walkforward loop — avoids loading
    100K+ entries into memory for the larger Stage 1 windows.
    """
    path = corpus_dir(corpus_id) / "entries.jsonl"
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield CorpusEntry.from_json_line(line)


def load_entries_by_decision(
    corpus_id: str,
    *,
    parse_clean_only: bool = True,
) -> dict[tuple[str, str], CorpusEntry]:
    """Load entries indexed by (as_of, ticker) for direct lookup.

    Args:
        corpus_id: corpus directory name under ARCIS_CORPUS_ROOT
        parse_clean_only: when True (default per pre-reg §A1.4), entries
            with parse_failed=1 are EXCLUDED from the returned dict. The
            backtester's primary-metric path consumes parse-clean only;
            the diagnostic path may load with parse_clean_only=False.

    Returns:
        Dict ``{(as_of, ticker): CorpusEntry}``. If multiple entries
        share a (as_of, ticker) key, the last-written wins (entries.jsonl
        order). This shouldn't happen in a properly-generated corpus and
        is treated as a soft warning.
    """
    out: dict[tuple[str, str], CorpusEntry] = {}
    for entry in iter_entries(corpus_id):
        if parse_clean_only and entry.parse_failed == 1:
            continue
        out[(entry.as_of, entry.ticker)] = entry
    return out
