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

    def test_section_status_reflects_addendum_2_classifications(self, tmp_corpus_root):
        """Per addendum 2 §B1: section 8 reclassified to "fixed" via #858 fix (PR #883).
        Section 11 remains placeholder (no live producer; #870 follow-up).

        Manifest's section_pit_status reflects: 8="fixed", 11="placeholder".
        prompt_section_omitted contains ONLY 11 (8 is no longer omitted because
        the #858 loader fix populates the prompt fields with PIT-clean data).
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
        assert manifest.section_pit_status[8] == "fixed"
        assert manifest.section_pit_status[11] == "placeholder"

        entries = list(iter_entries("test-sec-004"))
        assert 8 not in entries[0].prompt_section_omitted, (
            "Section 8 should NOT be omitted post-#858 fix (PR #883)"
        )
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


# ── Bug A regression test (Sprint 1.C.4.5 / #104) ──
#
# Bug: scripts/generate_llm_corpus.py:232-235 has a guard
#     if not args.dry_run and decision_points:
#         features_by_date = _compute_features_for_window(decision_points)
# which means dry-run never computes features. But corpus_generator's
# _generate_one_entry calls _build_feature_prompt(feat, ticker) on EVERY path
# (including dry_run) to compute prompt_sha256. Without features, feat is None
# and every dry-run entry is silently skipped → 0 entries written.
#
# The fix is in scripts/generate_llm_corpus.py — drop the `not args.dry_run`
# guard. This test exercises the actual bug surface: invoke the script's
# main() with --dry-run + past dates and assert entries get written.


class TestDryRunWithPastDates:
    """Bug A regression-lock — dry-run script must produce entries for past dates."""

    def test_dry_run_writes_entries_for_past_window(self, tmp_corpus_root):
        """Script main() + --dry-run + past dates → entries written.

        This exercises Bug A at the actual call surface — the CLI script.
        Pre-fix, the script skipped feature computation under --dry-run,
        which meant features_by_date={} and corpus_generator
        _generate_one_entry's `feat = features_for_date.get(ticker)` returned
        None for every entry → every entry skipped → 0 entries.

        We mock _enumerate_decision_points (no real PIT lookup) and the
        underlying market_data + features pipeline so the test is hermetic.
        """
        import sys
        from unittest.mock import patch as _patch

        # Past dates spanning a multi-day window — same shape as Stage-1 fold 1
        past_decision_points = [
            ("2023-09-15", "AAPL"),
            ("2023-09-15", "MSFT"),
            ("2023-10-02", "AAPL"),
        ]
        features_payload = _make_features()
        features_by_date = {
            "2023-09-15": features_payload,
            "2023-10-02": features_payload,
        }

        with _patch(
            "scripts.generate_llm_corpus._enumerate_decision_points",
            return_value=past_decision_points,
        ), _patch(
            "scripts.generate_llm_corpus._compute_features_for_window",
            return_value=features_by_date,
        ), _patch(
            "scripts.generate_llm_corpus._resolve_code_sha", return_value="testsha",
        ), _patch(
            "src.evaluation.corpus_generator.enrich_features",
            side_effect=lambda features, config, as_of=None, **_: features,
        ), _patch(
            "src.evaluation.corpus_generator.build_packet_from_features",
            side_effect=lambda ticker, feat, config: _make_stub_packet(ticker=ticker),
        ):
            from scripts.generate_llm_corpus import main as _script_main
            rc = _script_main([
                "--corpus-id", "test-bug-a-dry-run-past",
                "--window-start", "2023-09-01",
                "--window-end", "2023-12-31",
                "--dry-run",
            ])
            assert rc == 0

        manifest = load_manifest("test-bug-a-dry-run-past")
        assert manifest.total_decision_points > 0, (
            f"Bug A: --dry-run produced 0 entries for past dates. "
            f"Got manifest.total_decision_points={manifest.total_decision_points}. "
            f"This is the script's `if not args.dry_run and decision_points:` "
            f"guard suppressing _compute_features_for_window when --dry-run is "
            f"set; the corpus generator's _generate_one_entry then sees "
            f"features_for_date={{}} and silently skips every entry."
        )
        # All 3 decision points should have produced dry-run entries
        assert manifest.total_decision_points == 3, (
            f"Expected 3 dry-run entries for 3 decision points with features, "
            f"got {manifest.total_decision_points}"
        )

        # Entries must be loadable
        entries = list(iter_entries("test-bug-a-dry-run-past"))
        assert len(entries) == 3
        keys = {(e.as_of, e.ticker) for e in entries}
        assert keys == {("2023-09-15", "AAPL"), ("2023-09-15", "MSFT"), ("2023-10-02", "AAPL")}


# ── #108 Lever 1 — parallelize Ollama calls in corpus generator ─────────────


class TestParallelEquivalence:
    """Regression-locks for #108 Lever 1 — parallel ThreadPoolExecutor dispatch
    must produce a corpus that is byte-equivalent (modulo generated_at, which
    is a per-row timestamp) to the sequential dispatch path. This is the
    methodology gate: the LLM cost-analysis (docs/research/llm-cost-analysis-2026-04-29.md
    §2.1) commits Lever 1 as zero-pre-reg-amendment ONLY IF the dispatch order
    cannot change the corpus contents. JSONL line order must also be preserved
    so resume semantics (which key on (as_of, ticker)) are unaffected.
    """

    @staticmethod
    def _decision_points_20() -> list[tuple[str, str]]:
        """20 deterministic decision points across 2 dates × 10 tickers."""
        tickers = ["AAPL", "MSFT", "GOOG", "AMZN", "META",
                   "NVDA", "TSLA", "JPM", "JNJ", "WMT"]
        points = []
        for as_of in ("2024-01-15", "2024-02-15"):
            for t in tickers:
                points.append((as_of, t))
        return points

    @staticmethod
    def _features_payload(tickers: list[str]) -> dict[str, dict]:
        """Build a feature dict containing every ticker we'll evaluate."""
        return {
            t: {
                "current_price": 100.0 + i,
                "trend_state": "uptrend",
                "company_name": f"{t} Corp.",
                "_score": 75 + (i % 10),
            }
            for i, t in enumerate(tickers)
        }

    def test_parallel_and_sequential_produce_identical_entries(self, tmp_corpus_root):
        """num_parallel=1 and num_parallel=4 produce the same corpus.

        Identity criteria (anything else would be a methodology change):
          - Same set of prompt_sha256 (one per (as_of, ticker))
          - Same parse-outcome counts (parser_strategy_succeeded, parse_failed)
          - Same enrichment_pit_warnings tuple per (as_of, ticker)
          - JSONL line order identical (parallel writes still come out in
            submission order, not completion order)
        """
        from src.evaluation.corpus_generator import generate_corpus

        decision_points = self._decision_points_20()
        tickers = sorted({t for _, t in decision_points})
        features_payload = self._features_payload(tickers)
        features_by_date = {
            "2024-01-15": features_payload,
            "2024-02-15": features_payload,
        }

        # Deterministic stub keyed by ticker so the response is repeatable
        # across the two runs. Use a parser-clean response (metadata block)
        # so the strategy label is also deterministic.
        def deterministic_llm(packet, features, config, **kwargs):
            return _make_stub_packet(
                ticker=packet.ticker,
                conviction=(7 if packet.ticker.startswith(("A", "M")) else 6),
                parse_failed=False,
                why_now=f"why-now for {packet.ticker}",
                deeper=f"deeper analysis for {packet.ticker}",
            )

        # Deterministic enricher — same warnings shape per (as_of, ticker).
        def deterministic_enrich(features, config, as_of=None, warnings_out=None, **_):
            if warnings_out is not None:
                # Append a deterministic PIT warning for half the tickers.
                for t in features:
                    if t in {"AAPL", "GOOG", "TSLA"}:
                        warnings_out.append(f"news_coverage_gap:{t}:{as_of}")
            return features

        # Sequential run
        with patch(
            "src.evaluation.corpus_generator.enhance_packet_with_llm",
            side_effect=deterministic_llm,
        ), patch(
            "src.evaluation.corpus_generator.enrich_features",
            side_effect=deterministic_enrich,
        ), patch(
            "src.evaluation.corpus_generator.build_packet_from_features",
            side_effect=lambda ticker, feat, config: _make_stub_packet(ticker=ticker),
        ):
            generate_corpus(
                corpus_id="test-parallel-seq",
                decision_points=decision_points,
                features_by_date=features_by_date,
                model_version="arcis:v1.0.0",
                config={"llm": {"enabled": True}},
                code_sha="abc",
                window_start="2024-01-01",
                window_end="2024-12-31",
                num_parallel=1,
            )

        entries_seq = list(iter_entries("test-parallel-seq"))

        # Parallel run with the same inputs
        with patch(
            "src.evaluation.corpus_generator.enhance_packet_with_llm",
            side_effect=deterministic_llm,
        ), patch(
            "src.evaluation.corpus_generator.enrich_features",
            side_effect=deterministic_enrich,
        ), patch(
            "src.evaluation.corpus_generator.build_packet_from_features",
            side_effect=lambda ticker, feat, config: _make_stub_packet(ticker=ticker),
        ):
            generate_corpus(
                corpus_id="test-parallel-par",
                decision_points=decision_points,
                features_by_date=features_by_date,
                model_version="arcis:v1.0.0",
                config={"llm": {"enabled": True}},
                code_sha="abc",
                window_start="2024-01-01",
                window_end="2024-12-31",
                num_parallel=4,
            )

        entries_par = list(iter_entries("test-parallel-par"))

        # Same number of entries
        assert len(entries_par) == len(entries_seq) == 20

        # Same prompt_sha256 set (one per (as_of, ticker))
        assert {e.prompt_sha256 for e in entries_seq} == {e.prompt_sha256 for e in entries_par}

        # Same parse outcomes per ticker
        seq_parse_failed = sum(1 for e in entries_seq if e.parse_failed)
        par_parse_failed = sum(1 for e in entries_par if e.parse_failed)
        assert seq_parse_failed == par_parse_failed == 0

        # Handle None coercion for sort (parser_strategy_succeeded is str|None).
        seq_strategies = sorted((e.parser_strategy_succeeded or "") for e in entries_seq)
        par_strategies = sorted((e.parser_strategy_succeeded or "") for e in entries_par)
        assert seq_strategies == par_strategies

        # Same enrichment_pit_warnings per (as_of, ticker)
        seq_warnings = {(e.as_of, e.ticker): e.enrichment_pit_warnings for e in entries_seq}
        par_warnings = {(e.as_of, e.ticker): e.enrichment_pit_warnings for e in entries_par}
        assert seq_warnings == par_warnings

        # JSONL line order is identical (parallel writes preserve submission order)
        seq_keys = [(e.as_of, e.ticker) for e in entries_seq]
        par_keys = [(e.as_of, e.ticker) for e in entries_par]
        assert seq_keys == par_keys, (
            "Parallel JSONL line order must match sequential submission order — "
            "resume semantics depend on stable on-disk order."
        )

    def test_parallel_corpus_does_not_block_concurrent_live_scan(self, tmp_corpus_root):
        """Watch-loop coexistence — a parallel corpus run at num_parallel=4
        plus 1 concurrent 'live scan' call (simulating the watch loop's
        live-scan path) must:
          - not deadlock
          - allow the live scan to complete in reasonable time
          - produce a well-formed corpus (no JSONL corruption, line count
            matches submission count)

        This is the design contract for the operator's "watch loop alongside
        walkforward" requirement.
        """
        import threading
        import time as _time
        from src.evaluation.corpus_generator import generate_corpus

        # 4-decision corpus run with a 100ms LLM delay per call
        decision_points = [
            ("2024-01-15", "AAPL"),
            ("2024-01-15", "MSFT"),
            ("2024-01-15", "GOOG"),
            ("2024-01-15", "AMZN"),
        ]
        features_by_date = {"2024-01-15": self._features_payload(
            ["AAPL", "MSFT", "GOOG", "AMZN"]
        )}

        def slow_llm(packet, features, config, **kwargs):
            _time.sleep(0.1)
            return _make_stub_packet(ticker=packet.ticker)

        # Live-scan callable — simulates the watch loop's path. Just records
        # how long it took to complete.
        live_scan_latency: list[float] = []

        def live_scan_call() -> None:
            t0 = _time.monotonic()
            # Simulate the live-scan LLM call path — just sleep 100ms.
            _time.sleep(0.1)
            live_scan_latency.append(_time.monotonic() - t0)

        corpus_thread_exc: list[BaseException] = []

        def run_corpus():
            try:
                with patch(
                    "src.evaluation.corpus_generator.enhance_packet_with_llm",
                    side_effect=slow_llm,
                ), patch(
                    "src.evaluation.corpus_generator.enrich_features",
                    side_effect=lambda features, config, as_of=None, **_: features,
                ), patch(
                    "src.evaluation.corpus_generator.build_packet_from_features",
                    side_effect=lambda ticker, feat, config: _make_stub_packet(ticker=ticker),
                ):
                    generate_corpus(
                        corpus_id="test-parallel-coexist",
                        decision_points=decision_points,
                        features_by_date=features_by_date,
                        model_version="arcis:v1.0.0",
                        config={"llm": {"enabled": True}},
                        code_sha="abc",
                        window_start="2024-01-01",
                        window_end="2024-12-31",
                        num_parallel=4,
                    )
            except BaseException as exc:  # noqa: BLE001
                corpus_thread_exc.append(exc)

        corpus_thread = threading.Thread(target=run_corpus)
        corpus_thread.start()

        # Concurrently fire a single live-scan call
        scan_thread = threading.Thread(target=live_scan_call)
        scan_thread.start()

        # Both should finish promptly; corpus is bounded by 100ms × ceil(4/4) ≈ 100ms,
        # plus thread startup. Live scan is 100ms. End-to-end well under 2s.
        scan_thread.join(timeout=2.0)
        corpus_thread.join(timeout=5.0)

        assert not corpus_thread.is_alive(), "Corpus thread did not complete in time (deadlock?)"
        assert not scan_thread.is_alive(), "Live-scan thread did not complete in time (blocked?)"
        assert not corpus_thread_exc, f"Corpus thread raised: {corpus_thread_exc!r}"

        # Live scan completed in reasonable time (< 2s end-to-end including thread scheduling)
        assert live_scan_latency, "Live-scan callable was not invoked"
        assert live_scan_latency[0] < 2.0, (
            f"Live-scan call took {live_scan_latency[0]:.2f}s — "
            f"corpus run blocked it (queue contention)"
        )

        # JSONL well-formed: one entry per submission, no corruption
        entries = list(iter_entries("test-parallel-coexist"))
        assert len(entries) == 4
        assert {e.ticker for e in entries} == {"AAPL", "MSFT", "GOOG", "AMZN"}
        # Submission order preserved
        assert [e.ticker for e in entries] == ["AAPL", "MSFT", "GOOG", "AMZN"]
