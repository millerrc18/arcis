# Capability Registry — Deferred Backlog

**Date:** 2026-05-21
**Context:** The registry-refresh build (#88) landed the registry at **exactly 80**
capabilities (19 pre-existing + 47 firm-structural + 14 heterogeneous keep-set).
The heterogeneous keep-set was trimmed per-family (T5=3, T6=3, T7=3, T8=3, T9=2)
to hit 80 exactly; the second-tier entries below were **deliberately deferred**,
not lost. This is the on-the-record list so a future pass can register them.

Each module here is also seeded into `EXEMPT_MODULES` in
`tests/test_capability_registry_coverage.py` (Convention E) with a one-line
reason. **Promoting a deferred item later = remove its `EXEMPT_MODULES` entry
AND register it** — Convention E then *requires* its registration, so the
backlog can never silently re-drift.

The registry is therefore honestly at **80 / ~91**, with the remaining ~11
tracked here. (The deferred set spans more than 11 source files because some
proposed capabilities fold multiple support modules; the count below is by
proposed *capability*, matching design spec §3-defer.)

---

## Execution / exits (T5)

| Proposed capability | Source module | Proposed kind | Why deferred |
|---|---|---|---|
| `exit_reason_classifier` | `src/shadow_trading/exit_reason.py` | DECISION | Classification logic for why a position exited; second-tier vs. the kept `position_exit_manager` SYSTEM. |
| `decision_trade_alerts` | (alert wiring in execution path) | DECISION | Trade-alert routing decision; low marginal observability value this pass. |
| `bracket_monitor` | `src/shadow_trading/bracket_monitor.py` | SYSTEM | Bracket-order watchdog; covered operationally by the kept `position_exit_manager` SYSTEM. |

## Scan / LLM / council (T6)

| Proposed capability | Source module | Proposed kind | Why deferred |
|---|---|---|---|
| `candidate_ranking` | `src/ranking/ranker.py` | DECISION | Candidate scoring/ranking; no `ranking/capability_registration.py` host created this pass. |
| `build_watchlist` | `src/llm/watchlist_writer.py` | ACTION | Watchlist assembly; second-tier vs. the kept `build_decision_packet` ACTION. |
| `trade_postmortem` | `src/llm/postmortem_writer.py` | ACTION | LLM postmortem prose; reporting, not a live control surface. |
| `council_aggregation` | `src/council/aggregation.py` | DECISION | Vote-aggregation rule; folded conceptually under the kept `council_engine` SYSTEM. |
| `eod_recap` | (end-of-day recap path) | ACTION | EOD recap generation; reporting, low observability value. |

## Training (T7)

| Proposed capability | Source module | Proposed kind | Why deferred |
|---|---|---|---|
| `evaluate_holdout` | `src/evaluation/` holdout path | ACTION | Holdout evaluation; folded into the kept `model_promotion_gate` DECISION criteria. |
| `rollback_model` | trainer auto-rollback path | ACTION | Auto-rollback action; folded into `run_finetune` ACTION + `model_promotion_gate`. |
| `build_training_corpus` | `src/evaluation/corpus_generator.py`, `src/training/data_collector.py` | ACTION | Corpus assembly; second-tier vs. the kept `run_finetune` ACTION. |
| `run_dpo` | `src/training/dpo_pipeline.py` | ACTION | DPO fine-tuning pipeline; not on the active training path this pass. |

## Evaluation / audit (T8)

| Proposed capability | Source module | Proposed kind | Why deferred |
|---|---|---|---|
| `system_validator` | `src/evaluation/system_validator.py` | SYSTEM | Config/structure validator; second-tier vs. the kept `system_auditor` SYSTEM. |
| `walkforward_validation` | `src/evaluation/walkforward.py` | SYSTEM | Walk-forward validation engine; deferred pending the post-freeze walk-forward initiative. |
| `build_scorecard` | `src/evaluation/scorecard.py`, `src/evaluation/build_score.py` | ACTION | Scorecard rendering; reporting, not a live control surface. |
| `change_detector` | `src/evaluation/change_detector.py` | SYSTEM | Distribution-change detector; second-tier vs. the kept `model_monitor` SYSTEM. |
| `monte_carlo_sim` | (monte-carlo simulation path) | SYSTEM | Monte-Carlo risk simulation; offline analysis, low live-observability value. |

## Notifications / attribution (T9)

| Proposed capability | Source module | Proposed kind | Why deferred |
|---|---|---|---|
| `telegram_command_handler` | `src/notifications/telegram_commands.py` | ACTION | Inbound Telegram command dispatch; second-tier vs. the kept `telegram_notifier` SYSTEM. |
| `notification_policy` | `src/notifications/policy.py` | DECISION | Notification routing/dedup policy; decision surface deferred. |
| `platform_event_bus` | `src/notifications/platform_events.py` | SYSTEM | Internal event bus; infrastructure plumbing, low observability value. |
| `attribution_backtest` | (attribution backtest path) | ACTION | Attribution backtesting; offline analysis. |

---

## Promotion procedure

To register a deferred capability later:

1. Add its `register_*` call (directly in the module, or via the package's
   `capability_registration.py` thin-host).
2. Remove its entry from `EXEMPT_MODULES` in
   `tests/test_capability_registry_coverage.py` (Convention E).
3. Remove its row from this file.
4. Raise the integration-test floor in
   `tests/test_capability_registry_integration.py` if the count grows past the
   current `>= 80`.

Convention E will fail CI if a deferred module is un-EXEMPTed without being
registered, so steps 1 and 2 are coupled by design.
