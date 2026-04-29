"""Generate an LLM-scoring corpus for Stage 1 walk-forward (#96.2).

Operator-runnable CLI that wraps ``src.evaluation.corpus_generator.generate_corpus``.

The generator enumerates walk-forward decision points (one per (as_of, ticker)
pair across the OOS window's trading days × point-in-time SP100 universe),
calls the LLM at each with PIT-clean enrichment, and streams CorpusEntry
rows to ``data/corpus/<corpus_id>/entries.jsonl`` plus a manifest.

Usage::

    python scripts/generate_llm_corpus.py --corpus-id stage1-001 \\
        --window-start 2023-09-01 --window-end 2026-04-28

    # Plumbing test — no LLM calls
    python scripts/generate_llm_corpus.py --corpus-id smoke-001 \\
        --window-start 2024-01-01 --window-end 2024-01-31 --dry-run

    # Resume after crash
    python scripts/generate_llm_corpus.py --corpus-id stage1-001 \\
        --window-start 2023-09-01 --window-end 2026-04-28 --resume

Pre-reg addendum 1 §A1.1 binds ``model_version`` to a single value across the
entire walk-forward window. The default is ``arcis:v1.0.0`` per §A1.1
commitment; passing a different value requires a new pre-registration.
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from datetime import date
from pathlib import Path

# Allow running as a script: ensure repo root is on sys.path.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logger = logging.getLogger(__name__)


def _resolve_code_sha() -> str:
    """Return the current git SHA, or 'unknown' if git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=str(_REPO_ROOT),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return "unknown"


def _parse_folds(text: str | None) -> list[int] | None:
    """Parse ``1,2,3`` into [1, 2, 3]; None → None."""
    if not text:
        return None
    return [int(p.strip()) for p in text.split(",") if p.strip()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate an LLM-scoring corpus for Stage 1 walk-forward "
            "(per pre-reg addendum 1 §A1+§A3)."
        ),
    )
    parser.add_argument(
        "--corpus-id", required=True,
        help="Stable id for this corpus (becomes the directory name).",
    )
    parser.add_argument(
        "--window-start", required=True,
        help="ISO date — walk-forward window start (e.g., 2023-09-01).",
    )
    parser.add_argument(
        "--window-end", required=True,
        help="ISO date — walk-forward window end (e.g., 2026-04-28).",
    )
    parser.add_argument(
        "--model-version", default="arcis:v1.0.0",
        help=(
            "LLM model version (pre-reg §A1.1 binding; default: arcis:v1.0.0). "
            "Changing this requires a new pre-registration."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip the LLM and write placeholder entries (plumbing test only).",
    )
    parser.add_argument(
        "--max-decisions", type=int, default=None,
        help="Cap on number of decision points (for testing).",
    )
    parser.add_argument(
        "--folds", default=None,
        help="Comma-separated fold indices (1-based) to generate, e.g. '1,2,3'.",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help=(
            "Skip decision points already present in entries.jsonl. "
            "Use this to restart after a crash without redoing finished work."
        ),
    )
    parser.add_argument(
        "--log-level", default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR).",
    )
    return parser


def _enumerate_decision_points(
    *,
    window_start: str,
    window_end: str,
    folds: list[int] | None,
    max_decisions: int | None,
) -> list[tuple[str, str]]:
    """Build the (as_of, ticker) list for the walk-forward window.

    Strategy: iterate through the 8 walk-forward folds (per pre-reg §3.3)
    over the requested window. Within each fold's test span, take every
    trading day × point-in-time SP100 universe.

    This reuses ``src.evaluation.walkforward.compute_fold_boundaries`` so
    fold semantics stay consistent with the harness — see SIBLING-SEARCH
    note in the PR body.
    """
    from src.evaluation.walkforward import _is_trading_day, compute_fold_boundaries
    from src.universe.pit import get_sp100_at
    from datetime import date as _date, timedelta

    boundaries = compute_fold_boundaries(anchor=window_start)
    if folds is not None:
        # Convert 1-based indices to 0-based.
        boundaries = [b for b in boundaries if (b["fold_idx"] + 1) in folds]

    end_date = _date.fromisoformat(window_end)

    decision_points: list[tuple[str, str]] = []
    for fold in boundaries:
        ts = _date.fromisoformat(fold["test_start"])
        te = _date.fromisoformat(fold["test_end"])
        if te > end_date:
            te = end_date
        cursor = ts
        while cursor <= te:
            if _is_trading_day(cursor):
                as_of_str = cursor.isoformat()
                try:
                    universe = get_sp100_at(as_of_str)
                except Exception as exc:
                    logger.warning(
                        "[CORPUS] %s: PIT universe lookup failed (%s) — skipping",
                        as_of_str, exc,
                    )
                    cursor += timedelta(days=1)
                    continue
                for ticker in sorted(universe):
                    decision_points.append((as_of_str, ticker))
                    if max_decisions and len(decision_points) >= max_decisions:
                        return decision_points
            cursor += timedelta(days=1)
    return decision_points


def _compute_features_for_window(
    decision_points: list[tuple[str, str]],
) -> dict[str, dict[str, dict]]:
    """Compute features for each unique as_of in the decision list.

    Returns ``{as_of: {ticker: feature_dict}}``. This is the heavy lifting
    of corpus generation — the LLM-side cost is dominated by this side
    when running the full Stage 1 window.

    Sprint 1.C.4.5 / #104 — Bug B fix. Previously this used
    ``fetch_ohlcv(period="3y")`` which yfinance anchors to today's date,
    so for fold 1 (test_start=2023-09-01) the slice returned only ~88
    trading days — below slice_to_date's 200-row gate, causing every ticker
    to be filtered out and features_by_date to be empty. Now we anchor the
    fetch to (earliest_as_of - 280 calendar days) through (latest_as_of)
    so slice_to_date's 200-trading-day minimum is satisfied for the very
    first as_of cutoff. PIT cleanliness is still enforced at slice_to_date
    time (df.index <= cutoff).
    """
    from datetime import date as _date, timedelta as _timedelta

    from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark
    from src.features.engine import compute_all_features
    from src.training.historical_data import slice_to_date

    by_date: dict[str, dict[str, dict]] = {}
    if not decision_points:
        return by_date

    universe = sorted({t for _, t in decision_points})
    spans = sorted({d for d, _ in decision_points})
    earliest_as_of = _date.fromisoformat(spans[0])
    latest_as_of = _date.fromisoformat(spans[-1])
    fetch_start = (earliest_as_of - _timedelta(days=280)).isoformat()
    fetch_end = latest_as_of.isoformat()

    ohlcv = fetch_ohlcv(universe, start=fetch_start, end=fetch_end)
    spy = fetch_spy_benchmark(start=fetch_start, end=fetch_end)

    for as_of in spans:
        sliced, spy_sliced = slice_to_date({"tickers": ohlcv, "spy": spy}, as_of)
        if not sliced or spy_sliced.empty:
            continue
        by_date[as_of] = compute_all_features(sliced, spy_sliced, as_of=as_of)
    return by_date


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    from src.config import load_config
    from src.evaluation.corpus_generator import generate_corpus

    config = load_config()

    folds = _parse_folds(args.folds)

    logger.info(
        "[CORPUS] %s: enumerating decision points (window=%s..%s, folds=%s, max=%s)",
        args.corpus_id, args.window_start, args.window_end, folds, args.max_decisions,
    )
    decision_points = _enumerate_decision_points(
        window_start=args.window_start,
        window_end=args.window_end,
        folds=folds,
        max_decisions=args.max_decisions,
    )
    logger.info("[CORPUS] %d decision points enumerated", len(decision_points))

    features_by_date: dict[str, dict[str, dict]] = {}
    if decision_points:
        # Sprint 1.C.4.5 / #104 — Bug A fix. Previously this guard skipped
        # feature computation under --dry-run, but corpus_generator's
        # _generate_one_entry calls _build_feature_prompt(feat, ticker) on
        # every path (including dry-run) to compute prompt_sha256. Without
        # features, feat is None and every dry-run entry is silently skipped.
        # The "dry" in dry-run means "no LLM call" (per _dry_run_entry
        # placeholder), not "no feature pipeline".
        logger.info("[CORPUS] Computing features for %d unique dates", len({d for d, _ in decision_points}))
        features_by_date = _compute_features_for_window(decision_points)

    code_sha = _resolve_code_sha()

    result_path = generate_corpus(
        corpus_id=args.corpus_id,
        decision_points=decision_points,
        features_by_date=features_by_date,
        model_version=args.model_version,
        config=config,
        code_sha=code_sha,
        window_start=args.window_start,
        window_end=args.window_end,
        dry_run=args.dry_run,
        resume=args.resume,
    )
    logger.info("[CORPUS] Wrote corpus to %s", result_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
