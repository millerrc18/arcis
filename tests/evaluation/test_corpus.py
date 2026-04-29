"""Tests for src/evaluation/corpus.py (#96.1 Sprint 1.C Phase 4 foundation).

Locks the binding storage contract from pre-reg addendum 1 §A3:
- CorpusEntry validates canonical actions + 1-10 conviction range + 64-char SHA
- JSONL round-trip is byte-stable
- CorpusManifest serializes/parses cleanly with int section keys preserved
- compute_admissibility encodes §A1.4 parse-failure ceiling + §A2.1 broken-section gate
- write_corpus + iter_entries + load_entries_by_decision form a complete read/write loop
- parse_clean_only filter on load_entries_by_decision is on-by-default per §A1.4
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.evaluation.corpus import (
    CorpusEntry,
    CorpusManifest,
    compute_admissibility,
    iter_entries,
    load_entries_by_decision,
    load_manifest,
    write_corpus,
)


# ── Test fixture helpers ─────────────────────────────────────────────────────


def _entry(
    *,
    as_of: str = "2024-06-15",
    ticker: str = "AAPL",
    model_version: str = "arcis:v1.0.0",
    prompt_sha256: str = "a" * 64,
    response: str = "Conviction: 7\nWhy now: ...\nDeeper analysis: ...",
    llm_action: str = "taken",
    llm_conviction: int = 7,
    parse_failed: int = 0,
    parser_strategy_succeeded: str | None = "metadata_block",
    prompt_section_omitted: tuple[int, ...] = (),
    enrichment_pit_warnings: tuple[str, ...] = (),
    generated_at: str = "2026-04-29T12:00:00Z",
) -> CorpusEntry:
    return CorpusEntry(
        as_of=as_of,
        ticker=ticker,
        model_version=model_version,
        prompt_sha256=prompt_sha256,
        response=response,
        llm_action=llm_action,
        llm_conviction=llm_conviction,
        parse_failed=parse_failed,
        parser_strategy_succeeded=parser_strategy_succeeded,
        prompt_section_omitted=prompt_section_omitted,
        enrichment_pit_warnings=enrichment_pit_warnings,
        generated_at=generated_at,
    )


def _manifest(
    *,
    corpus_id: str = "test-corpus-001",
    total: int = 100,
    pf_count: int = 2,
    section_pit_status: dict[int, str] | None = None,
    coverage_limit_hits: dict[str, int] | None = None,
) -> CorpusManifest:
    section = section_pit_status or {1: "clean", 2: "clean", 4: "fixed", 5: "fixed",
                                       6: "fixed", 7: "fixed", 8: "placeholder",
                                       9: "best-effort", 10: "fixed", 11: "placeholder"}
    coverage = coverage_limit_hits or {}
    pf_rate = pf_count / total if total else 0.0
    return CorpusManifest(
        corpus_id=corpus_id,
        generated_at="2026-04-29T12:00:00Z",
        code_sha="abc123def456",
        model_version="arcis:v1.0.0",
        walkforward_window_start="2023-09-01",
        walkforward_window_end="2026-04-28",
        total_decision_points=total,
        parse_failure_count=pf_count,
        parse_failure_rate=pf_rate,
        section_pit_status=section,
        coverage_limit_hits=coverage,
        admissibility=compute_admissibility(pf_rate, section),
    )


@pytest.fixture
def tmp_corpus_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override ARCIS_CORPUS_ROOT so writes land in a tmp dir."""
    root = tmp_path / "corpus_root"
    root.mkdir()
    monkeypatch.setenv("ARCIS_CORPUS_ROOT", str(root))
    return root


# ── CorpusEntry validation ──────────────────────────────────────────────────


class TestCorpusEntryValidation:
    def test_valid_entry_constructs(self):
        entry = _entry()
        assert entry.llm_action == "taken"
        assert entry.llm_conviction == 7
        assert entry.parse_failed == 0

    def test_non_canonical_action_rejected(self):
        with pytest.raises(ValueError, match="not canonical"):
            _entry(llm_action="buy")

    def test_each_canonical_action_accepted(self):
        for action in ("taken", "rejected", "parse_failed", "conviction_none"):
            entry = _entry(llm_action=action)
            assert entry.llm_action == action

    def test_conviction_below_range_rejected(self):
        with pytest.raises(ValueError, match="outside 1-10"):
            _entry(llm_conviction=0)

    def test_conviction_above_range_rejected(self):
        with pytest.raises(ValueError, match="outside 1-10"):
            _entry(llm_conviction=11)

    def test_parse_failed_must_be_0_or_1(self):
        with pytest.raises(ValueError, match="must be 0 or 1"):
            _entry(parse_failed=2)

    def test_prompt_sha256_must_be_64_chars(self):
        with pytest.raises(ValueError, match="64-char hex digest"):
            _entry(prompt_sha256="abc")


# ── JSONL round-trip ─────────────────────────────────────────────────────────


class TestEntryJsonRoundTrip:
    def test_roundtrip_preserves_all_fields(self):
        original = _entry(
            prompt_section_omitted=(8, 11),
            enrichment_pit_warnings=("section_5_finnhub_coverage_limit",),
        )
        line = original.to_json_line()
        restored = CorpusEntry.from_json_line(line)
        assert restored == original

    def test_roundtrip_handles_empty_collections(self):
        original = _entry(
            prompt_section_omitted=(),
            enrichment_pit_warnings=(),
        )
        restored = CorpusEntry.from_json_line(original.to_json_line())
        assert restored.prompt_section_omitted == ()
        assert restored.enrichment_pit_warnings == ()

    def test_roundtrip_preserves_parser_strategy_none(self):
        original = _entry(parser_strategy_succeeded=None, parse_failed=1)
        restored = CorpusEntry.from_json_line(original.to_json_line())
        assert restored.parser_strategy_succeeded is None

    def test_jsonl_line_has_no_internal_newlines(self):
        """JSONL is one-entry-per-line — embedded newlines would break stream-read."""
        entry = _entry(response="line1\nline2\nline3")
        line = entry.to_json_line()
        assert "\n" not in line


# ── CorpusManifest round-trip + admissibility ───────────────────────────────


class TestManifest:
    def test_roundtrip_preserves_int_section_keys(self):
        """JSON serializes int dict keys as strings — int restoration matters
        because backtester filters by section number, not 'section_4' string."""
        original = _manifest()
        text = original.to_json()
        restored = CorpusManifest.from_json(text)
        assert restored == original
        # Specifically — keys must be int after restore
        assert all(isinstance(k, int) for k in restored.section_pit_status.keys())

    def test_is_admissible_pass(self):
        m = _manifest(pf_count=2, total=100)
        assert m.admissibility == "PASS"
        assert m.is_admissible() is True

    def test_is_admissible_fail(self):
        # 6 parse failures / 100 = 6% > 5% ceiling
        m = _manifest(pf_count=6, total=100)
        assert "FAIL" in m.admissibility
        assert m.is_admissible() is False


# ── compute_admissibility rules (per pre-reg §A1.4 + §A2.1) ─────────────────


class TestComputeAdmissibility:
    def test_parse_rate_at_ceiling_passes(self):
        """5% exactly is allowed; >5% is FAIL."""
        result = compute_admissibility(
            parse_failure_rate=0.05,
            section_pit_status={1: "clean", 4: "fixed"},
        )
        assert result == "PASS"

    def test_parse_rate_above_ceiling_fails(self):
        result = compute_admissibility(
            parse_failure_rate=0.0501,
            section_pit_status={1: "clean"},
        )
        assert result.startswith("FAIL")
        assert "parse_failure_rate" in result
        assert "0.05" in result

    def test_broken_section_fails(self):
        result = compute_admissibility(
            parse_failure_rate=0.0,
            section_pit_status={1: "clean", 4: "broken", 5: "fixed"},
        )
        assert result.startswith("FAIL")
        assert "[4]" in result

    def test_multiple_broken_sections_listed(self):
        result = compute_admissibility(
            parse_failure_rate=0.0,
            section_pit_status={1: "clean", 4: "broken", 5: "broken", 7: "fixed"},
        )
        assert "[4, 5]" in result

    def test_placeholder_and_accepted_stale_pass(self):
        """Section 8 placeholder + Section 3 sectors-accepted-stale should not fail."""
        result = compute_admissibility(
            parse_failure_rate=0.0,
            section_pit_status={
                1: "clean", 2: "clean", 3: "accepted-stale",
                4: "fixed", 5: "fixed", 6: "fixed", 7: "fixed",
                8: "placeholder", 9: "best-effort", 10: "fixed", 11: "placeholder",
            },
        )
        assert result == "PASS"

    def test_parse_failure_takes_precedence_over_broken_section(self):
        """When BOTH conditions fail, the parse-failure-rate message is reported.

        Either failure blocks; this just locks the message-priority for callers
        that surface a single reason in dashboards / Stage 1 admissibility logs.
        """
        result = compute_admissibility(
            parse_failure_rate=0.10,
            section_pit_status={4: "broken"},
        )
        assert result.startswith("FAIL: parse_failure_rate")


# ── write_corpus + iter_entries + load_entries_by_decision ──────────────────


class TestCorpusReadWrite:
    def test_write_then_iter_returns_same_entries(self, tmp_corpus_root):
        entries = [
            _entry(ticker="AAPL", as_of="2024-06-15"),
            _entry(ticker="MSFT", as_of="2024-06-15"),
            _entry(ticker="AAPL", as_of="2024-06-16"),
        ]
        write_corpus("test-corpus-001", entries, _manifest(corpus_id="test-corpus-001"))

        loaded = list(iter_entries("test-corpus-001"))
        assert len(loaded) == 3
        # Entries should round-trip identically
        for orig, restored in zip(entries, loaded):
            assert orig == restored

    def test_load_manifest_round_trips(self, tmp_corpus_root):
        m = _manifest(corpus_id="test-corpus-002")
        write_corpus("test-corpus-002", [_entry()], m)
        loaded = load_manifest("test-corpus-002")
        assert loaded == m

    def test_load_entries_by_decision_filters_parse_failed_by_default(
        self, tmp_corpus_root
    ):
        """Pre-reg §A1.4: parse_failed=1 rows excluded from primary metric.

        load_entries_by_decision is the primary-metric reader; default
        parse_clean_only=True ensures backtester can't accidentally
        include parse-failure rows.
        """
        clean = _entry(ticker="AAPL", as_of="2024-06-15", parse_failed=0)
        polluted = _entry(
            ticker="MSFT",
            as_of="2024-06-15",
            parse_failed=1,
            llm_action="taken",
            llm_conviction=5,  # parser fallback
            parser_strategy_succeeded=None,
        )
        write_corpus(
            "test-corpus-003",
            [clean, polluted],
            _manifest(corpus_id="test-corpus-003"),
        )

        # Default: parse-failed excluded
        idx = load_entries_by_decision("test-corpus-003")
        assert ("2024-06-15", "AAPL") in idx
        assert ("2024-06-15", "MSFT") not in idx

        # Diagnostic mode: include all
        idx_all = load_entries_by_decision("test-corpus-003", parse_clean_only=False)
        assert ("2024-06-15", "AAPL") in idx_all
        assert ("2024-06-15", "MSFT") in idx_all

    def test_iter_entries_skips_blank_lines(self, tmp_corpus_root):
        """Tolerate trailing newline / blank lines from text editors."""
        write_corpus(
            "test-corpus-004",
            [_entry()],
            _manifest(corpus_id="test-corpus-004"),
        )
        # Append a blank line (mimics editor save)
        path = tmp_corpus_root / "test-corpus-004" / "entries.jsonl"
        path.write_text(path.read_text() + "\n\n", encoding="utf-8")
        # Should still parse the one valid entry without raising on the blank
        loaded = list(iter_entries("test-corpus-004"))
        assert len(loaded) == 1


# ── Cross-module canonical-action drift detection ───────────────────────────


class TestCanonicalActionDrift:
    """Locks against drift between corpus.py and src/attribution/logger.py.

    Both modules define a frozenset of canonical llm_action values;
    keeping them in sync without sharing imports keeps corpus.py
    dependency-free at import time. This test catches drift.
    """

    def test_canonical_actions_match_attribution_logger(self):
        from src.attribution.logger import _CANONICAL_LLM_ACTIONS as ATTR_ACTIONS
        from src.evaluation.corpus import _CANONICAL_ACTIONS as CORPUS_ACTIONS

        assert ATTR_ACTIONS == CORPUS_ACTIONS, (
            "Canonical action sets drifted between attribution/logger.py and "
            "evaluation/corpus.py — adding one without the other will break "
            "either the writer (CorpusEntry validation) or the reader."
        )
