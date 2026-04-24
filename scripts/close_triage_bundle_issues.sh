#!/usr/bin/env bash
# Closes all 29 issues fixed in fix/triage-bundle-1-4-2026-04-23.
# Run AFTER the branch is pushed so the comments link to commits.
set -euo pipefail

BRANCH="fix/triage-bundle-1-4-2026-04-23"

# Phase A — Tier 3 dep-health (13)
declare -A A_ISSUES=(
  [527]="bare ImportError: pass for pysentiment2 → logger.debug"
  [544]="unused import json removed from fundamentals.py"
  [545]="enricher Telegram alert failures → logger.debug"
  [546]="yfinance auto_adjust FutureWarning suppressed at module load"
  [572]="psycopg2-binary added to requirements.txt"
  [587]="features.earnings already logs (regression guard added)"
  [588]="close_shadow_trade exit-metadata failures → _logger.warning"
  [589]="features.engine sector context already logs (regression guard added)"
  [590]="5 raw sqlite3.connect call sites migrated to connect_db()"
  [599]="llama-cpp-python added to requirements.txt with platform marker"
  [600]="torch added to requirements.txt"
  [601]="LLM client active-model lookup → logger.debug"
  [605]="ranker.py classify_regime + sector context except → logger.debug"
)

# Phase B — Tier 1 observability (4)
declare -A B_ISSUES=(
  [613]="log_activity now refuses writes under PYTEST_CURRENT_TEST unless ARCIS_LOG_ACTIVITY_IN_PYTEST=1; cleanup script for 540 polluted rows in scripts/"
  [614]="SCAN_COMPLETE / TRADE_OPENED / TRADE_CLOSED / RISK_ALERT / SYSTEM_EVENT all wired to writers"
  [618]="_is_likely_sleep_gap helper compares against 1.5×scan_interval, eliminates 12×/day false alerts"
  [623]="_is_collector_error helper interrogates dict structure instead of substring match"
)

# Phase C — Tier 2 safety (2)
declare -A C_ISSUES=(
  [438]="risk governor explicitly rejects when equity<=0; pre-fix size_ok=True was a fail-open"
  [440]="bearer token comparison now uses hmac.compare_digest (constant-time)"
)

# Phase D — Tier 4 scoped (4)
declare -A D_ISSUES=(
  [576]="actions.router gated through verify_local_token (opt-in via ARCIS_LOCAL_API_TOKEN)"
  [598]="3 platform.py POST endpoints have Depends(verify_auth); cloud_app overrides via dependency_overrides"
  [624]="_resolve_stuck_pnl returns None when price unknown; reconcile writes NULL pnl instead of $0"
  [622]="confirmed all signal.signal calls in watch.py wrapped in try/except ValueError; regression guard added"
)

# Original session work (6) — already in commits but not yet GH-closed
declare -A E_ISSUES=(
  [608]="exit-overshoot fixed via #609 cancel-return-value handling + #610 retry counter"
  [609]="cancel_paper_order's terminal_state response now read; routes to _close_from_broker_fill"
  [610]="exit_retry_count increments in first-time exit path; abandons after MAX_EXIT_RETRIES"
  [612]="ClaudeAuthError typed exception raised on credit/auth failures; CouncilUnavailableError raised in aggregation when all assessments parse-failed"
  [615]="CollectionResult dataclass + structured overnight payload; ERROR + Telegram on is_silent_failure"
  [616]="OUTPUT FORMAT (HARD) sections added to outcome_prompts + QUALITY_ENHANCEMENT_PROMPT"
  [630]="src/utils/deploy_info.py + log_deployment_info wired into cmd_startup; emits banner + activity_log row"
)

close_one () {
  local n="$1"
  local note="$2"
  local tier="$3"
  echo "Closing #$n ($tier)..."
  gh issue close "$n" --comment "Resolved in branch \`$BRANCH\`. $note. See branch commits for the full diff and regression-guard tests."
}

for n in "${!A_ISSUES[@]}"; do close_one "$n" "${A_ISSUES[$n]}" "Tier 3"; done
for n in "${!B_ISSUES[@]}"; do close_one "$n" "${B_ISSUES[$n]}" "Tier 1"; done
for n in "${!C_ISSUES[@]}"; do close_one "$n" "${C_ISSUES[$n]}" "Tier 2"; done
for n in "${!D_ISSUES[@]}"; do close_one "$n" "${D_ISSUES[$n]}" "Tier 4"; done
for n in "${!E_ISSUES[@]}"; do close_one "$n" "${E_ISSUES[$n]}" "Earlier session"; done

echo "Done. 29 issues closed."
