"""Tests for src/evaluation/corpus_generator.py (#96.2 Sprint 1.C Phase 4).

Locks the LLM-scoring corpus generator contract from pre-reg addendum 1 §A1+§A3:

- generate_corpus produces a valid corpus directory (entries.jsonl + manifest.json)
- parse_failed flag round-trips from stubbed packet to CorpusEntry
- as_of is forwarded to enrich_features for each decision point (PIT discipline)
- dry_run path doesn't call the LLM
- resume path skips entries already present in entries.jsonl
- Manifest's section_pit_status reflects the §A1.3 placeholder treatment
- Admissibility verdict in manifest matches compute_admissibility()
- Generator raises ValueError when model_version is None (per §A1.1 rule)
- Cross-module integration: generate small corpus → load via iter_entries

LLM is mocked via unittest.mock — no real Ollama calls per CLAUDE.md.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.evaluation.corpus import (
    CorpusManifest,
    iter_entries,
    load_entries_by_decision,
    load_manifest,
)


# ── Test fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_corpus_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override ARCIS_CORPUS_ROOT so writes land in a tmp dir."""
    root = tmp_path / "corpus_root"
    root.mkdir()
    monkeypatch.setenv("ARCIS_CORPUS_ROOT", str(root))
    return root


def _make_stub_packet(
    *,
    ticker: str = "AAPL",
    conviction: int = 7,
    parse_failed: bool = False,
    why_now: str = "Stub why-now reason",
    deeper: str = "Stub deeper analysis",
) -> Any:
    """Build a packet-like object that mirrors what enhance_packet_with_llm returns."""
    pkt = MagicMock()
    pkt.ticker = ticker
    pkt.llm_conviction = conviction
    pkt.llm_conviction_parse_failed = parse_failed
    pkt.llm_conviction_reason = "stub-reason"
    pkt.llm_timeout_days = 5
    pkt.why_now = why_now
    pkt.deeper_analysis = deeper
    pkt.confidence = 7
    pkt.entry_zone = "$100.00"
    pkt.stop_invalidation = "$95.00"
    pkt.targets = "$110.00"
    pkt.event_risk = "Low"
    pkt.position_sizing = MagicMock(
        allocation_dollars=5000.0, allocation_pct=5.0, estimated_risk_dollars=250.0,
    )
    return pkt


def _make_decision_points(n: int = 3) -> list[tuple[str, str]]:
    """Generate a small list of (as_of, ticker) decision points."""
    base = [
        ("2024-01-15", "AAPL"),
        ("2024-01-15", "MSFT"),
        ("2024-02-15", "AAPL"),
    ]
    return base[:n]


def _make_features() -> dict[str, dict]:
    """Build minimal feature dict for a single ticker."""
    return {
        "AAPL": {
            "current_price": 150.0,
            "trend_state": "uptrend",
            "company_name": "Apple Inc.",
            "_score": 80,
        },
        "MSFT": {
            "current_price": 300.0,
            "trend_state": "uptrend",
            "company_name": "Microsoft Corp.",
            "_score": 75,
        },
    }


# ── generate_corpus core path ────────────────────────────────────────────────


class TestGenerateCorpusCore:
    def test_writes_entries_and_manifest_to_corpus_dir(self, tmp_corpus_root):
        """Smoke test: generator creates entries.jsonl + manifest.json."""
        from src.evaluation.corpus_generator import generate_corpus

        with patch(
            "src.evaluation.corpus_generator.enhance_packet_with_llm",
            side_effect=lambda packet, features, config: _make_stub_packet(
                ticker=packet.ticker,
            ),
        ), patch(
            "src.evaluation.corpus_generator.enrich_features",
            side_effect=lambda features, config, as_of=None, **_: features,
        ), patch(
            "src.evaluation.corpus_generator.build_packet_from_features",
            side_effect=lambda ticker, feat, config: _make_stub_packet(ticker=ticker),
        ):
            result = generate_corpus(
                corpus_id="test-gen-001",
                decision_points=_make_decision_points(2),
                features_by_date={"2024-01-15": _make_features()},
                model_version="arcis:v1.0.0",
                config={"llm": {"enabled": True}},
                code_sha="testsha123",
                window_start="2024-01-01",
                window_end="2024-12-31",
            )

        # Returns the corpus directory path
        assert result.exists()
        assert (result / "entries.jsonl").exists()
        assert (result / "manifest.json").exists()

        # Entries are loadable + ordered as written
        entries = list(iter_entries("test-gen-001"))
        assert len(entries) == 2
        tickers = {e.ticker for e in entries}
        assert tickers == {"AAPL", "MSFT"}

    def test_parse_failed_round_trips_from_packet_to_entry(self, tmp_corpus_root):
        """If stub packet sets llm_conviction_parse_failed=True, entry.parse_failed==1."""
        from src.evaluation.corpus_generator import generate_corpus

        def stub_llm(packet, features, config):
            # AAPL parses cleanly, MSFT fails parse
            failed = packet.ticker == "MSFT"
            return _make_stub_packet(
                ticker=packet.ticker,
                conviction=5 if failed else 7,
                parse_failed=failed,
            )

        with patch(
            "src.evaluation.corpus_generator.enhance_packet_with_llm",
            side_effect=stub_llm,
        ), patch(
            "src.evaluation.corpus_generator.enrich_features",
            side_effect=lambda features, config, as_of=None, **_: features,
        ), patch(
            "src.evaluation.corpus_generator.build_packet_from_features",
            side_effect=lambda ticker, feat, config: _make_stub_packet(ticker=ticker),
        ):
            generate_corpus(
                corpus_id="test-pf-002",
                decision_points=_make_decision_points(2),
                features_by_date={"2024-01-15": _make_features()},
                model_version="arcis:v1.0.0",
                config={"llm": {"enabled": True}},
                code_sha="abc",
                window_start="2024-01-01",
                window_end="2024-12-31",
            )

        all_entries = load_entries_by_decision("test-pf-002", parse_clean_only=False)
        clean = load_entries_by_decision("test-pf-002", parse_clean_only=True)

        # Both rows are present in the diagnostic load
        assert ("2024-01-15", "AAPL") in all_entries
        assert ("2024-01-15", "MSFT") in all_entries

        # Only AAPL passes the parse-clean filter (default per §A1.4)
        assert ("2024-01-15", "AAPL") in clean
        assert ("2024-01-15", "MSFT") not in clean

        # parse_failed is 0/1 per CorpusEntry contract
        assert all_entries[("2024-01-15", "AAPL")].parse_failed == 0
        assert all_entries[("2024-01-15", "MSFT")].parse_failed == 1

    def test_as_of_is_forwarded_to_enrich_features(self, tmp_corpus_root):
        """Critical PIT plumbing: each decision point's as_of must reach enricher."""
        from src.evaluation.corpus_generator import generate_corpus

        captured_as_of: list[str | None] = []

        def stub_enrich(features, config, as_of=None, **_):
            captured_as_of.append(as_of)
            return features

        with patch(
            "src.evaluation.corpus_generator.enhance_packet_with_llm",
            side_effect=lambda packet, features, config: _make_stub_packet(ticker=packet.ticker),
        ), patch(
            "src.evaluation.corpus_generator.enrich_features",
            side_effect=stub_enrich,
        ), patch(
            "src.evaluation.corpus_generator.build_packet_from_features",
            side_effect=lambda ticker, feat, config: _make_stub_packet(ticker=ticker),
        ):
            generate_corpus(
                corpus_id="test-asof-003",
                decision_points=[("2024-01-15", "AAPL"), ("2024-02-20", "MSFT")],
                features_by_date={
                    "2024-01-15": _make_features(),
                    "2024-02-20": _make_features(),
                },
                model_version="arcis:v1.0.0",
                config={"llm": {"enabled": True}},
                code_sha="abc",
                window_start="2024-01-01",
                window_end="2024-12-31",
            )

        # Both decision points' as_of strings must appear in the captured list
        assert "2024-01-15" in captured_as_of
        assert "2024-02-20" in captured_as_of
        # No call should have been made with as_of=None — that would be PIT violation
        assert None not in captured_as_of

    def test_section_8_and_11_recorded_as_omitted_per_addendum(self, tmp_corpus_root):
        """Per §A1.3 + §A2.2: sections 8 + 11 have no live producer; recorded as omitted.

        Manifest's section_pit_status reflects this: 8="placeholder", 11="placeholder".
        Each entry's prompt_section_omitted contains 8 and 11.
        """
        from src.evaluation.corpus_generator import generate_corpus

        with patch(
            "src.evaluation.corpus_generator.enhance_packet_with_llm",
            side_effect=lambda packet, features, config: _make_stub_packet(ticker=packet.ticker),
        ), patch(
            "src.evaluation.corpus_generator.enrich_features",
            side_effect=lambda features, config, as_of=None, **_: features,
        ), patch(
            "src.evaluation.corpus_generator.build_packet_from_features",
            side_effect=lambda ticker, feat, config: _make_stub_packet(ticker=ticker),
        ):
            generate_corpus(
                corpus_id="test-sec-004",
                decision_points=[("2024-01-15", "AAPL")],
                features_by_date={"2024-01-15": _make_features()},
                model_version="arcis:v1.0.0",
                config={"llm": {"enabled": True}},
                code_sha="abc",
                window_start="2024-01-01",
                window_end="2024-12-31",
            )

        manifest = load_manifest("test-sec-004")
        assert manifest.section_pit_status[8] == "placeholder"
        assert manifest.section_pit_status[11] == "placeholder"

        entries = list(iter_entries("test-sec-004"))
        assert 8 in entries[0].prompt_section_omitted
        assert 11 in entries[0].prompt_section_omitted

    def test_admissibility_in_manifest_matches_computed_value(self, tmp_corpus_root):
        """Manifest.admissibility == compute_admissibility(parse_rate, sections)."""
        from src.evaluation.corpus_generator import generate_corpus

        with patch(
            "src.evaluation.corpus_generator.enhance_packet_with_llm",
            side_effect=lambda packet, features, config: _make_stub_packet(
                ticker=packet.ticker,
            ),
        ), patch(
            "src.evaluation.corpus_generator.enrich_features",
            side_effect=lambda features, config, as_of=None, **_: features,
        ), patch(
            "src.evaluation.corpus_generator.build_packet_from_features",
            side_effect=lambda ticker, feat, config: _make_stub_packet(ticker=ticker),
        ):
            generate_corpus(
                corpus_id="test-adm-005",
                decision_points=_make_decision_points(2),
                features_by_date={"2024-01-15": _make_features()},
                model_version="arcis:v1.0.0",
                config={"llm": {"enabled": True}},
                code_sha="abc",
                window_start="2024-01-01",
                window_end="2024-12-31",
            )

        # All clean parses → PASS
        m = load_manifest("test-adm-005")
        from src.evaluation.corpus import compute_admissibility
        expected = compute_admissibility(m.parse_failure_rate, m.section_pit_status)
        assert m.admissibility == expected
        assert m.is_admissible() is True


# ── Validation: model_version is required (§A1.1) ───────────────────────────


class TestModelVersionRequired:
    def test_none_model_version_raises(self, tmp_corpus_root):
        """Per pre-reg §A1.1, the corpus is bound to one model version. None forbidden."""
        from src.evaluation.corpus_generator import generate_corpus

        with pytest.raises(ValueError, match="model_version"):
            generate_corpus(
                corpus_id="test-mv-006",
                decision_points=_make_decision_points(1),
                features_by_date={"2024-01-15": _make_features()},
                model_version=None,
                config={"llm": {"enabled": True}},
                code_sha="abc",
                window_start="2024-01-01",
                window_end="2024-12-31",
            )

    def test_empty_model_version_raises(self, tmp_corpus_root):
        from src.evaluation.corpus_generator import generate_corpus

        with pytest.raises(ValueError, match="model_version"):
            generate_corpus(
                corpus_id="test-mv-007",
                decision_points=_make_decision_points(1),
                features_by_date={"2024-01-15": _make_features()},
                model_version="",
                config={"llm": {"enabled": True}},
                code_sha="abc",
                window_start="2024-01-01",
                window_end="2024-12-31",
            )


# ── dry_run path ─────────────────────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_does_not_call_llm(self, tmp_corpus_root):
        """When dry_run=True, the LLM enhancement function is NOT called."""
        from src.evaluation.corpus_generator import generate_corpus

        llm_mock = MagicMock(side_effect=AssertionError("LLM must not be called in dry_run"))
        with patch(
            "src.evaluation.corpus_generator.enhance_packet_with_llm", llm_mock
        ), patch(
            "src.evaluation.corpus_generator.enrich_features",
            side_effect=lambda features, config, as_of=None, **_: features,
        ), patch(
            "src.evaluation.corpus_generator.build_packet_from_features",
            side_effect=lambda ticker, feat, config: _make_stub_packet(ticker=ticker),
        ):
            generate_corpus(
                corpus_id="test-dry-008",
                decision_points=_make_decision_points(2),
                features_by_date={"2024-01-15": _make_features()},
                model_version="arcis:v1.0.0",
                config={"llm": {"enabled": True}},
                code_sha="abc",
                window_start="2024-01-01",
                window_end="2024-12-31",
                dry_run=True,
            )

        # LLM was not called
        llm_mock.assert_not_called()
        # Manifest still got written
        m = load_manifest("test-dry-008")
        assert m.corpus_id == "test-dry-008"


# ── resume path ──────────────────────────────────────────────────────────────


class TestResume:
    def test_resume_skips_existing_entries(self, tmp_corpus_root):
        """When resume=True and entries.jsonl already has (as_of, ticker), skip it."""
        from src.evaluation.corpus_generator import generate_corpus

        # First run: 2 entries
        call_log_1: list[tuple[str, str]] = []

        def stub_llm_1(packet, features, config):
            call_log_1.append((packet.ticker, str(features.get("__as_of__", ""))))
            return _make_stub_packet(ticker=packet.ticker)

        with patch(
            "src.evaluation.corpus_generator.enhance_packet_with_llm", side_effect=stub_llm_1
        ), patch(
            "src.evaluation.corpus_generator.enrich_features",
            side_effect=lambda features, config, as_of=None, **_: features,
        ), patch(
            "src.evaluation.corpus_generator.build_packet_from_features",
            side_effect=lambda ticker, feat, config: _make_stub_packet(ticker=ticker),
        ):
            generate_corpus(
                corpus_id="test-resume-009",
                decision_points=[("2024-01-15", "AAPL"), ("2024-01-15", "MSFT")],
                features_by_date={"2024-01-15": _make_features()},
                model_version="arcis:v1.0.0",
                config={"llm": {"enabled": True}},
                code_sha="abc",
                window_start="2024-01-01",
                window_end="2024-12-31",
            )

        first_call_count = len(call_log_1)
        assert first_call_count == 2

        # Second run with resume=True + 3 decision points; only the new MSFT-2024-02-15 should call LLM
        call_log_2: list[tuple[str, str]] = []

        def stub_llm_2(packet, features, config):
            call_log_2.append((packet.ticker, "second-pass"))
            return _make_stub_packet(ticker=packet.ticker)

        with patch(
            "src.evaluation.corpus_generator.enhance_packet_with_llm", side_effect=stub_llm_2
        ), patch(
            "src.evaluation.corpus_generator.enrich_features",
            side_effect=lambda features, config, as_of=None, **_: features,
        ), patch(
            "src.evaluation.corpus_generator.build_packet_from_features",
            side_effect=lambda ticker, feat, config: _make_stub_packet(ticker=ticker),
        ):
            generate_corpus(
                corpus_id="test-resume-009",
                decision_points=[
                    ("2024-01-15", "AAPL"),
                    ("2024-01-15", "MSFT"),
                    ("2024-02-15", "AAPL"),
                ],
                features_by_date={
                    "2024-01-15": _make_features(),
                    "2024-02-15": _make_features(),
                },
                model_version="arcis:v1.0.0",
                config={"llm": {"enabled": True}},
                code_sha="abc",
                window_start="2024-01-01",
                window_end="2024-12-31",
                resume=True,
            )

        # Only the new (2024-02-15, AAPL) should have re-called LLM
        assert len(call_log_2) == 1
        assert call_log_2[0][0] == "AAPL"

        # Final corpus has all 3 entries
        entries = list(iter_entries("test-resume-009"))
        keys = {(e.as_of, e.ticker) for e in entries}
        assert keys == {("2024-01-15", "AAPL"), ("2024-01-15", "MSFT"), ("2024-02-15", "AAPL")}


# ── Cross-module integration ────────────────────────────────────────────────


class TestIntegrationWithCorpusReader:
    def test_generated_corpus_is_loadable_by_iter_entries(self, tmp_corpus_root):
        """End-to-end: generate a small corpus, load via iter_entries — entries match."""
        from src.evaluation.corpus_generator import generate_corpus

        with patch(
            "src.evaluation.corpus_generator.enhance_packet_with_llm",
            side_effect=lambda packet, features, config: _make_stub_packet(
                ticker=packet.ticker, conviction=8,
            ),
        ), patch(
            "src.evaluation.corpus_generator.enrich_features",
            side_effect=lambda features, config, as_of=None, **_: features,
        ), patch(
            "src.evaluation.corpus_generator.build_packet_from_features",
            side_effect=lambda ticker, feat, config: _make_stub_packet(ticker=ticker),
        ):
            generate_corpus(
                corpus_id="test-int-010",
                decision_points=_make_decision_points(3),
                features_by_date={
                    "2024-01-15": _make_features(),
                    "2024-02-15": _make_features(),
                },
                model_version="arcis:v1.0.0",
                config={"llm": {"enabled": True}},
                code_sha="abc",
                window_start="2024-01-01",
                window_end="2024-12-31",
            )

        entries = list(iter_entries("test-int-010"))
        assert len(entries) == 3
        # All entries have the correct model_version
        assert all(e.model_version == "arcis:v1.0.0" for e in entries)
        # All entries have a 64-char SHA prompt hash
        assert all(len(e.prompt_sha256) == 64 for e in entries)
        # llm_conviction was passed from packet (8)
        assert all(e.llm_conviction == 8 for e in entries)


# ── CLI surface ──────────────────────────────────────────────────────────────


class TestCLI:
    def test_script_help_runs(self):
        """The CLI script must respond to --help without import errors."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "scripts/generate_llm_corpus.py", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "--corpus-id" in result.stdout
        assert "--window-start" in result.stdout
        assert "--window-end" in result.stdout
        assert "--dry-run" in result.stdout
        assert "--resume" in result.stdout
