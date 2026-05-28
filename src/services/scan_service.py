"""Scan pipeline service.

Called by: api.routes.actions, api.routes.scan, cli.commands
Calls: data_enrichment.enricher, data_ingestion.market_data, data_integrity, email.notifier, features.engine, features.event_risk_score, features.traffic_light, journal.store, llm.packet_writer, notifications.telegram, packets.template, ranking.ranker, shadow_trading.executor, training.versioning, universe.company_names, universe.sp100
Owns tables: none
Config keys: enabled, event_risk, shadow_trading
Tests: tests/test_services.py
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from src.notifications import safe_send
from src.notifications.telegram import send_telegram

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

if TYPE_CHECKING:
    from src.platform.strategy_spec import StrategySpec


def _route_packet_email(
    *, ticker: str, subject: str, rendered: str,
    via_cli: bool, send_email_flag: bool,
) -> bool:
    """DD-13/DD-25/DD-30: route action_packet email to direct-send OR digest.

    Returns True iff a delivery (direct or enqueue) was performed.
    """
    from src.email.notifier import send_email
    if send_email_flag or via_cli:
        return bool(send_email(subject, rendered))
    try:
        from src.notifications.email_digest import enqueue_for_email_digest
        enqueue_for_email_digest(
            "action_packet", severity="normal",
            payload={"ticker": ticker, "rendered": rendered, "subject": subject},
            source_tag="email:postclose",
        )
        return True
    except (ImportError, ModuleNotFoundError) as err:
        logger.critical("[SCAN] email_digest unavailable for %s — fallback: %s", ticker, err)
        try:
            safe_send("action_packet", ticker=ticker, subject=subject)
        except Exception as _safe_err:
            logger.warning("[SCAN] safe_send fallback failed: %s", _safe_err)
        return bool(send_email(subject, rendered))


def _log_regime_capture_failure(ticker: str, feat: dict) -> None:
    """Forensic logging for the regime_at_entry NULL class (2026-05-17).

    Live PG state showed 13 of 18 OPEN shadow trades on 2026-05-15 with
    regime_at_entry=NULL. The investigation pinned the writer at
    src/shadow_trading/executor.py:1116 which reads
    feat["traffic_light"]["regime_label"] and falls back to "" when the
    enrichment chain (src/features/enrichment.py:_apply_traffic_light) has
    failed. The chain depends on FRED credit data, SPY OHLCV, and the
    traffic_light_state singleton — any one of which can be missing or
    intermittently unreachable.

    This helper emits a WARNING with the sorted feat keys so an operator
    auditing the watch log after the next scan cycle can see exactly which
    enrichment step short-circuited. Only fires when BOTH `regime` and
    `market_regime` keys are missing or falsy — by then both the Telegram
    notification (feat.get("regime") or feat.get("market_regime")) and the
    DB writer (feat["traffic_light"]["regime_label"]) have already lost
    the regime signal silently.

    See docs/audits/2026-05-17-v0.36.13-training-page/regime_capture_followup.md
    for the cross-subsystem analysis.
    """
    if not feat.get("regime") and not feat.get("market_regime"):
        try:
            keys = sorted(feat.keys())
        except Exception:
            keys = []
        logger.warning(
            "[SCAN] regime_at_entry NULL for %s — feat keys=%s",
            ticker, keys,
        )


def _resolve_attribution_hooks(
    strategy: "StrategySpec" | None,
) -> tuple[bool, bool]:
    if strategy is None:
        return True, True

    raw = getattr(strategy, "raw", {}) or {}
    hooks = (raw.get("hooks") or {}).get("attribution", [])
    if not isinstance(hooks, list):
        return False, False
    return "log_before_llm" in hooks, "log_after_llm" in hooks


def _persist_recommendation(packet, feat: dict, candidate: dict, enriched_prompt: str):
    """Write the recommendation row for a scored packet and return its id.

    Keeps the ``log_recommendation`` call (with the full llm_conviction_reason /
    llm_timeout_days kwarg set) pinned in this module so the call-site
    regression-locks (tests/services/test_scan_service_persistence.py) keep
    asserting against scan_service.py.
    """
    from src.journal.store import log_recommendation
    from src.training.versioning import get_active_model_name
    model_ver = get_active_model_name()
    return log_recommendation(
        packet, feat, candidate["score"], candidate["qualification"],
        model_version=model_ver,
        enriched_prompt=enriched_prompt,
        llm_conviction=getattr(packet, 'llm_conviction', None),
        llm_conviction_reason=getattr(packet, 'llm_conviction_reason', None),
        llm_timeout_days=getattr(packet, 'llm_timeout_days', None),
    )


def _emit_trade_opened_telegram(
    ticker: str, feat: dict, candidate: dict, packet,
) -> None:
    """Emit the enriched ``trade_opened`` Telegram notification for an opened
    shadow trade.

    Carries the W21 P2-1 ``regime_at_entry`` capture so the regression-lock
    (tests/services/test_scan_service_regime_keys.py) keeps the corrected
    enricher-key read pinned in this module.
    """
    from src.shadow_trading.executor import _parse_price
    _entry = _parse_price(packet.entry_zone)
    _stop = _parse_price(packet.stop_invalidation)
    _target = _parse_price(packet.targets.split("/")[0])
    _shares = max(1, int(packet.position_sizing.allocation_dollars / _entry)) if _entry > 0 else 1
    # Enriched context: sector/regime/vix/conviction from the
    # feature row; concurrent position count from shadow_trades.
    try:
        from src.journal.store import get_open_shadow_trades
        _concurrent = len(get_open_shadow_trades())
    except Exception:
        _concurrent = None
    _log_regime_capture_failure(ticker, feat)
    safe_send(
        "trade_opened",
        ticker=ticker, entry_price=_entry, stop=_stop, target=_target,
        score=int(candidate["score"]), shares=_shares,
        setup_type=feat.get("setup_type"),
        setup_confidence=feat.get("setup_confidence"),
        sector=feat.get("sector") or feat.get("realized_sector"),
        # W21 P2-1 fix (2026-05-18): the enricher writes the regime
        # label to `feat["traffic_light"]["regime_label"]` (3-label
        # GREEN/YELLOW/RED vocabulary) and `feat["regime_label"]`
        # (5-label calm_uptrend/etc.). The pre-fix ternary read
        # non-existent keys (`feat["regime"]`, `feat["market_regime"]`),
        # so this Telegram-side payload was NULL even on healthy
        # enrichment runs. See regime_capture_followup.md from
        # v0.36.13 T6 Path B for the full investigation.
        regime_at_entry=(
            (feat.get("traffic_light") or {}).get("regime_label")
            or feat.get("regime_label")
        ),
        vix_at_entry=feat.get("vix"),
        concurrent_positions=_concurrent,
        llm_conviction=candidate.get("llm_conviction"),
    )


def run_scan(
    config: dict,
    dry_run: bool = False,
    send_email_flag: bool = False,
    run_shadow: bool = True,
    strategy: "StrategySpec" | None = None,
    via_cli: bool = False,
) -> dict:
    """Execute the full scan pipeline and return structured results.

    Returns a dict with keys: timestamp, tickers_scanned, tickers_succeeded, tickers_failed,
    packet_worthy (list of dicts with ticker, score, qualification, features, packet_rendered, earnings_risk),
    watchlist (list of dicts), packets_generated, packets_emailed, shadow_trades_opened, shadow_trades_closed, model_version

    Phase 5 PR-C T15 (KC-12 / DA9): orchestrates the three phase helpers in
    src/services/_scan_service_impl.py — collect (universe + features +
    ranking), score (per-candidate packet/LLM/shadow loop), and persist
    (trade management + watchlist + result assembly).
    """
    from src.services._scan_service_impl import (
        _phase_collect,
        _phase_persist,
        _phase_score,
    )
    from src.training.versioning import get_active_model_name

    collected = _phase_collect(config, dry_run, strategy)
    if collected["abort"]:
        return {
            "timestamp": collected["now"].isoformat(),
            "tickers_scanned": len(collected["universe"]),
            "tickers_succeeded": collected["succeeded"],
            "tickers_failed": collected["failed"],
            "packet_worthy": [],
            "watchlist": [],
            "packets_generated": 0,
            "packets_emailed": 0,
            "shadow_trades_opened": 0,
            "shadow_trades_closed": 0,
            "model_version": get_active_model_name(),
        }

    candidates = collected["candidates"]
    score_result = _phase_score(
        config, dry_run, send_email_flag, run_shadow, strategy,
        via_cli=via_cli, candidates=candidates,
    )
    return _phase_persist(
        config, dry_run, run_shadow, candidates, score_result,
        scan_meta=collected, ranked=collected["ranked"],
    )
