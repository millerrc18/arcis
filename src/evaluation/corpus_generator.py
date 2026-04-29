"""LLM-scoring corpus generator (#96.2 Sprint 1.C Phase 4).

Module that enumerates walk-forward decision points, calls the LLM at each,
and streams ``CorpusEntry`` rows to ``data/corpus/<corpus_id>/entries.jsonl``
plus a final ``manifest.json``.

Called by: scripts/generate_llm_corpus.py (operator-runnable CLI)
Calls: src.evaluation.corpus, src.data_enrichment.enricher,
       src.llm.packet_writer, src.packets.template
Owns tables: none
Config keys: llm.enabled, data_enrichment.* (passthrough)
Tests: tests/evaluation/test_corpus_generator.py

The contract (pre-reg addendum 1 §A1 + §A3):

- §A1.1 — model_version is REQUIRED at call time. None or empty rejected.
- §A1.2 — temperature MUST be 0 in the LLM client config (caller's config).
- §A1.3 — prompt format is FROZEN at v0.32.0. We use ``_build_feature_prompt``
  exactly as-is. Sections 8 (options) and 11 (cross-asset) have no live
  producer; their feature dict keys are absent so ``_build_feature_prompt``
  emits ``n/a`` placeholders at the same character offset. We RECORD this
  as ``prompt_section_omitted=(8, 11)`` on every entry and as
  ``section_pit_status[8]="placeholder"`` + ``[11]="placeholder"`` in the
  manifest.
- §A1.4 — parse_failed reads from ``packet.llm_conviction_parse_failed``.
- §A2.1 — PIT plumbing: each decision point's ``as_of`` is forwarded to
  ``enrich_features(features, config, as_of=<as_of>)`` so the historical
  decision point gets PIT-clean enrichment.
- §A3.1 — per-decision artifact requirements (matched 1:1 to CorpusEntry).
- §A3.2 — reproducibility receipts (matched 1:1 to CorpusManifest).

Section status mapping written to manifest (per addendum §A2):

- Section 1 (technical) — ``clean`` (yfinance OHLCV is auto-adjusted, accepted
  per §A2.2)
- Section 2 (regime) — ``clean``
- Section 3 (sector) — ``accepted-stale`` (#861, accepted per §A2.2)
- Sections 4, 5, 6, 7, 10 — ``fixed`` (Sprint 1.C Phase 2 fixes #854-#859 wired)
- Section 8 (options) — ``placeholder`` (no live producer, §A2.2)
- Section 9 (events) — ``best-effort`` (#860 audit pending, §A2.2)
- Section 11 (cross-asset) — ``placeholder`` (no live producer, §A2.2)

Two follow-ups out of scope per dispatch:

- ``parser_strategy_succeeded`` field is stored as ``None`` because
  ``packet_writer._parse_llm_response`` doesn't currently track which of the
  6 conviction-parse strategies succeeded. Tracker filed.
- ``enrichment_pit_warnings`` is stored as ``()`` because individual
  ``fetch_*`` functions in ``src/data_enrichment/`` don't currently emit a
  warnings list. Tracker filed.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Module-level imports of the LLM + enrichment + packet builder so tests
# can monkeypatch the names on this module rather than chasing the original
# definition sites.
from src.data_enrichment.enricher import enrich_features
from src.evaluation.corpus import (
    CorpusEntry,
    CorpusManifest,
    compute_admissibility,
    corpus_dir,
    iter_entries,
)
from src.llm.packet_writer import _build_feature_prompt, enhance_packet_with_llm
from src.packets.template import build_packet_from_features

logger = logging.getLogger(__name__)


# Per addendum 1 §A1.3 + addendum 2 §B1 — only sections without a live
# producer are recorded as omitted on every entry. Section 8 was reclassified
# to "fixed" by addendum-2 §B1.1 once the #858 Option A loader fix landed
# (PR #883), so it's no longer in this tuple. Section 11 remains placeholder
# per §B1.3 (no live producer; #870 follow-up not blocking Stage 1).
_OMITTED_SECTIONS: tuple[int, ...] = (11,)

# Per addendum §A2 / §B1 — corpus generator is the writer of section_pit_status.
# Drift between this constant and the audit doc is caught at corpus
# admissibility time.
_SECTION_PIT_STATUS: dict[int, str] = {
    1: "clean",          # §A2.3 (yfinance auto-adjust accepted per §A2.2)
    2: "clean",          # §A2.3
    3: "accepted-stale", # §A2.2 — sector PIT history not built
    4: "fixed",          # §A2.1 — #856
    5: "fixed",          # §A2.1 — #857
    6: "fixed",          # §A2.1 — #854
    7: "fixed",          # §A2.1 — #855
    8: "fixed",          # addendum-2 §B1.1 — #858 Option A (PR #883)
    9: "best-effort",    # addendum-2 §B1.2 — operator repopulates earnings_calendar
    10: "fixed",         # §A2.1 — #859
    11: "placeholder",   # addendum-2 §B1.3 — no live producer (#870 follow-up)
}


def _resolve_llm_action(packet: Any) -> str:
    """Map a packet's parse outcome + conviction to a canonical llm_action.

    Per attribution/logger.py canonical set: taken / rejected / parse_failed
    / conviction_none. The corpus generator's policy mirrors the wired
    runtime callsites (universe_scanner.py, scan_service.py):

    - parse_failed=True AND conviction parse strategy returned no value → ``parse_failed``
    - parse_failed=True AND default conviction=5 was applied → ``parse_failed``
    - parse_failed=False AND conviction is None → ``conviction_none``
    - parse_failed=False AND conviction in [1, 10] → ``taken``

    A row marked ``rejected`` is reserved for callers that decide not to log
    a recommendation (rec_id IS NULL); the corpus generator always logs the
    decision point so ``rejected`` is never produced here.
    """
    parse_failed = bool(getattr(packet, "llm_conviction_parse_failed", False))
    conviction = getattr(packet, "llm_conviction", None)
    if parse_failed:
        return "parse_failed"
    if conviction is None:
        return "conviction_none"
    return "taken"


def _clamp_conviction(value: Any) -> int:
    """Coerce a packet's conviction to an int in [1, 10] for CorpusEntry."""
    if value is None:
        return 5
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return 5
    if ivalue < 1:
        return 1
    if ivalue > 10:
        return 10
    return ivalue


def _existing_decision_keys(corpus_id: str) -> set[tuple[str, str]]:
    """Return the (as_of, ticker) keys already present in entries.jsonl.

    Used by the resume path to skip work that's already done. Returns an
    empty set if entries.jsonl is absent.
    """
    path = corpus_dir(corpus_id) / "entries.jsonl"
    if not path.exists():
        return set()
    keys: set[tuple[str, str]] = set()
    for entry in iter_entries(corpus_id):
        keys.add((entry.as_of, entry.ticker))
    return keys


def _dry_run_entry(
    *, as_of: str, ticker: str, model_version: str, prompt_sha256: str,
) -> CorpusEntry:
    """Build a placeholder CorpusEntry for the dry-run path.

    The response field is empty, parse_failed=0, conviction=5 (midpoint /
    no opinion). This shape is for end-to-end plumbing testing only, NOT
    for primary-metric consumption.
    """
    return CorpusEntry(
        as_of=as_of,
        ticker=ticker,
        model_version=model_version,
        prompt_sha256=prompt_sha256,
        response="",
        llm_action="conviction_none",
        llm_conviction=5,
        parse_failed=0,
        parser_strategy_succeeded=None,
        prompt_section_omitted=_OMITTED_SECTIONS,
        enrichment_pit_warnings=(),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def _packet_to_entry(
    *, as_of: str, ticker: str, model_version: str, prompt_sha256: str, packet: Any,
) -> CorpusEntry:
    """Convert an enhanced packet into a CorpusEntry."""
    response_text = ""
    for attr in ("why_now", "deeper_analysis"):
        text = getattr(packet, attr, None)
        if text:
            response_text += (text + "\n")
    response_text = response_text.rstrip("\n")
    return CorpusEntry(
        as_of=as_of,
        ticker=ticker,
        model_version=model_version,
        prompt_sha256=prompt_sha256,
        response=response_text,
        llm_action=_resolve_llm_action(packet),
        llm_conviction=_clamp_conviction(getattr(packet, "llm_conviction", None)),
        parse_failed=1 if bool(getattr(packet, "llm_conviction_parse_failed", False)) else 0,
        parser_strategy_succeeded=None,  # see module docstring follow-up tracker
        prompt_section_omitted=_OMITTED_SECTIONS,
        enrichment_pit_warnings=(),  # see module docstring follow-up tracker
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def _generate_one_entry(
    *,
    as_of: str,
    ticker: str,
    features_for_date: dict[str, dict],
    model_version: str,
    config: dict,
    dry_run: bool,
) -> CorpusEntry | None:
    """Build a single CorpusEntry for one (as_of, ticker) decision point.

    Returns None if the ticker has no features for this date (decision point
    is skipped entirely — this should be rare; the caller's enumeration
    ought to have filtered already).
    """
    feat = features_for_date.get(ticker)
    if feat is None:
        logger.debug("[CORPUS] %s %s: no features — skipping", as_of, ticker)
        return None

    # PIT plumbing: route this date's enrichment through the as_of-aware
    # path. Sprint 1.C Phase 2 fixes (#854-#859) wired sections 4, 5, 6, 7,
    # 10 to honor as_of; sections 1, 2 are intrinsically PIT-clean; sections
    # 3, 8, 9, 11 are documented exceptions per §A2.
    enrich_features({ticker: feat}, config, as_of=as_of)

    # Build the prompt EXACTLY as runtime does — addendum §A1.3 freezes
    # this format. Sections 8 + 11 emit ``n/a`` placeholders naturally
    # because feat lacks options/cross-asset keys; we record them as
    # ``prompt_section_omitted`` so the manifest has explicit provenance.
    prompt = _build_feature_prompt(feat, ticker)
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    if dry_run:
        return _dry_run_entry(
            as_of=as_of, ticker=ticker, model_version=model_version,
            prompt_sha256=prompt_sha256,
        )

    packet = build_packet_from_features(ticker, feat, config)
    if packet is None:
        logger.debug("[CORPUS] %s %s: build_packet returned None — skipping", as_of, ticker)
        return None
    enhanced = enhance_packet_with_llm(packet, feat, config)
    return _packet_to_entry(
        as_of=as_of, ticker=ticker, model_version=model_version,
        prompt_sha256=prompt_sha256, packet=enhanced,
    )


def _stream_entries(
    *,
    corpus_id: str,
    decision_points: Iterable[tuple[str, str]],
    features_by_date: dict[str, dict[str, dict]],
    model_version: str,
    config: dict,
    dry_run: bool,
    resume: bool,
) -> tuple[int, int]:
    """Stream-write entries.jsonl. Returns (total_written, parse_failure_count).

    Honors resume by reading existing keys from disk and skipping; opens
    entries.jsonl in append mode when keys already present, otherwise
    overwrites (clean run).
    """
    root = corpus_dir(corpus_id)
    root.mkdir(parents=True, exist_ok=True)
    entries_path = root / "entries.jsonl"

    skip_keys: set[tuple[str, str]] = set()
    open_mode = "w"
    if resume:
        skip_keys = _existing_decision_keys(corpus_id)
        if skip_keys:
            open_mode = "a"
            logger.info(
                "[CORPUS] Resume: %d entries already present, will skip", len(skip_keys)
            )

    total = 0
    parse_failure_count = 0
    with entries_path.open(open_mode, encoding="utf-8") as fh:
        for as_of, ticker in decision_points:
            if (as_of, ticker) in skip_keys:
                continue
            entry = _generate_one_entry(
                as_of=as_of,
                ticker=ticker,
                features_for_date=features_by_date.get(as_of, {}),
                model_version=model_version,
                config=config,
                dry_run=dry_run,
            )
            if entry is None:
                continue
            fh.write(entry.to_json_line() + "\n")
            total += 1
            if entry.parse_failed == 1:
                parse_failure_count += 1

    if resume and skip_keys:
        # Re-count from disk so manifest totals include resumed entries.
        on_disk_total = 0
        on_disk_failures = 0
        for entry in iter_entries(corpus_id):
            on_disk_total += 1
            if entry.parse_failed == 1:
                on_disk_failures += 1
        return on_disk_total, on_disk_failures
    return total, parse_failure_count


def _build_and_write_manifest(
    *,
    corpus_id: str,
    code_sha: str,
    model_version: str,
    window_start: str,
    window_end: str,
    total: int,
    parse_failure_count: int,
) -> CorpusManifest:
    """Build the CorpusManifest + write manifest.json. Returns the manifest."""
    parse_failure_rate = parse_failure_count / total if total else 0.0
    section_status = dict(_SECTION_PIT_STATUS)
    admissibility = compute_admissibility(parse_failure_rate, section_status)
    manifest = CorpusManifest(
        corpus_id=corpus_id,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        code_sha=code_sha,
        model_version=model_version,
        walkforward_window_start=window_start,
        walkforward_window_end=window_end,
        total_decision_points=total,
        parse_failure_count=parse_failure_count,
        parse_failure_rate=parse_failure_rate,
        section_pit_status=section_status,
        coverage_limit_hits={},  # see follow-up: no fetcher emits warnings yet
        admissibility=admissibility,
    )
    root = corpus_dir(corpus_id)
    (root / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    logger.info(
        "[CORPUS] %s: %d entries, %d parse-failures (%.2f%%), admissibility=%s",
        corpus_id, total, parse_failure_count, 100 * parse_failure_rate, admissibility,
    )
    return manifest


def generate_corpus(
    *,
    corpus_id: str,
    decision_points: Iterable[tuple[str, str]],
    features_by_date: dict[str, dict[str, dict]],
    model_version: str | None,
    config: dict,
    code_sha: str,
    window_start: str,
    window_end: str,
    dry_run: bool = False,
    resume: bool = False,
) -> Path:
    """Generate an LLM-scoring corpus for Stage 1 walk-forward.

    See module docstring for the full contract. ``model_version`` MUST be
    a non-empty string per pre-reg §A1.1 — None or empty raises ValueError.

    Returns the path to the corpus directory (entries.jsonl + manifest.json).
    """
    if not model_version:
        raise ValueError(
            "model_version is required by pre-reg addendum §A1.1 — the corpus "
            "is bound to one model version. Pass model_version='arcis:v1.0.0' "
            "(or whichever single version is under test)."
        )
    total, parse_failure_count = _stream_entries(
        corpus_id=corpus_id,
        decision_points=decision_points,
        features_by_date=features_by_date,
        model_version=model_version,
        config=config,
        dry_run=dry_run,
        resume=resume,
    )
    _build_and_write_manifest(
        corpus_id=corpus_id,
        code_sha=code_sha,
        model_version=model_version,
        window_start=window_start,
        window_end=window_end,
        total=total,
        parse_failure_count=parse_failure_count,
    )
    return corpus_dir(corpus_id)
