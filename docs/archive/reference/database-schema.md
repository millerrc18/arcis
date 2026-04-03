# Database Schema

> Auto-generated from `src/schema/registry.py` — 46 tables

> Run `python scripts/generate_schema_docs.py` to regenerate


## Trading Core

### `bracket_health`

Bracket order health checks for open positions

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `check_id` | TEXT | **No** |  |  |
| `trade_id` | TEXT | **No** |  |  |
| `ticker` | TEXT | **No** |  |  |
| `stop_leg_status` | TEXT | Yes |  |  |
| `target_leg_status` | TEXT | Yes |  |  |
| `bracket_intact` | INTEGER | Yes | `1` |  |
| `action_taken` | TEXT | Yes |  |  |
| `checked_at` | TEXT | **No** |  |  |

### `recommendations` | Sync: incremental

LLM-generated trade recommendations with full context and outcomes

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `recommendation_id` | TEXT | **No** |  |  |
| `created_at` | TEXT | **No** |  |  |
| `ticker` | TEXT | **No** |  |  |
| `company_name` | TEXT | Yes |  |  |
| `mode` | TEXT | Yes |  |  |
| `setup_type` | TEXT | Yes |  |  |
| `priority_score` | REAL | Yes |  |  |
| `confidence_score` | REAL | Yes |  |  |
| `packet_type` | TEXT | Yes |  |  |
| `price_at_recommendation` | REAL | Yes |  |  |
| `market_regime` | TEXT | Yes |  |  |
| `sector_context` | TEXT | Yes |  |  |
| `trend_state` | TEXT | Yes |  |  |
| `relative_strength_state` | TEXT | Yes |  |  |
| `pullback_depth_pct` | REAL | Yes |  |  |
| `atr` | REAL | Yes |  |  |
| `volume_state` | TEXT | Yes |  |  |
| `recommendation` | TEXT | Yes |  |  |
| `thesis_text` | TEXT | Yes |  |  |
| `entry_zone` | TEXT | Yes |  |  |
| `stop_level` | TEXT | Yes |  |  |
| `target_1` | TEXT | Yes |  |  |
| `target_2` | TEXT | Yes |  |  |
| `expected_hold_period` | TEXT | Yes |  |  |
| `position_size_dollars` | REAL | Yes |  |  |
| `position_size_pct` | REAL | Yes |  |  |
| `estimated_dollar_risk` | REAL | Yes |  |  |
| `reasons_to_trade` | TEXT | Yes |  |  |
| `reasons_to_pass` | TEXT | Yes |  |  |
| `earnings_date` | TEXT | Yes |  |  |
| `event_risk_flag` | TEXT | Yes |  |  |
| `hold_window_overlaps_earnings` | INTEGER | Yes |  |  |
| `event_risk_warning_text` | TEXT | Yes |  |  |
| `conservative_sizing_applied` | INTEGER | Yes |  |  |
| `packet_sent` | INTEGER | Yes |  |  |
| `packet_sent_at` | TEXT | Yes |  |  |
| `ryan_approved` | INTEGER | Yes |  |  |
| `ryan_executed` | INTEGER | Yes |  |  |
| `ryan_notes` | TEXT | Yes |  |  |
| `shadow_entry_price` | REAL | Yes |  |  |
| `shadow_entry_time` | TEXT | Yes |  |  |
| `shadow_exit_price` | REAL | Yes |  |  |
| `shadow_exit_time` | TEXT | Yes |  |  |
| `shadow_pnl_dollars` | REAL | Yes |  |  |
| `shadow_pnl_pct` | REAL | Yes |  |  |
| `max_favorable_excursion` | REAL | Yes |  |  |
| `max_adverse_excursion` | REAL | Yes |  |  |
| `shadow_duration_days` | REAL | Yes |  |  |
| `thesis_success` | INTEGER | Yes |  |  |
| `assistant_postmortem` | TEXT | Yes |  |  |
| `lesson_tag` | TEXT | Yes |  |  |
| `user_grade` | TEXT | Yes |  |  |
| `repeatable_setup` | INTEGER | Yes |  |  |
| `model_version` | TEXT | Yes |  |  |
| `enriched_prompt` | TEXT | Yes |  |  |
| `llm_conviction` | INTEGER | Yes |  |  |
| `llm_conviction_reason` | TEXT | Yes |  |  |

**Indexes:** `idx_recommendations_ticker`, `idx_recommendations_created_at`

### `shadow_trades` | Sync: incremental

Paper/shadow trades tracked from entry to exit with execution quality

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `trade_id` | TEXT | **No** |  |  |
| `recommendation_id` | TEXT | Yes |  |  |
| `ticker` | TEXT | **No** |  |  |
| `direction` | TEXT | Yes | `long` |  |
| `status` | TEXT | Yes | `pending` |  |
| `entry_price` | REAL | Yes |  |  |
| `stop_price` | REAL | Yes |  |  |
| `target_1` | REAL | Yes |  |  |
| `target_2` | REAL | Yes |  |  |
| `planned_shares` | INTEGER | Yes |  |  |
| `planned_allocation` | REAL | Yes |  |  |
| `actual_entry_price` | REAL | Yes |  |  |
| `actual_entry_time` | TEXT | Yes |  |  |
| `actual_exit_price` | REAL | Yes |  |  |
| `actual_exit_time` | TEXT | Yes |  |  |
| `exit_reason` | TEXT | Yes |  |  |
| `pnl_dollars` | REAL | Yes |  |  |
| `pnl_pct` | REAL | Yes |  |  |
| `max_favorable_excursion` | REAL | Yes |  |  |
| `max_adverse_excursion` | REAL | Yes |  |  |
| `duration_days` | INTEGER | Yes |  |  |
| `earnings_adjacent` | INTEGER | Yes | `0` |  |
| `created_at` | TEXT | **No** |  |  |
| `updated_at` | TEXT | **No** |  |  |
| `alpaca_order_id` | TEXT | Yes |  |  |
| `order_type` | TEXT | Yes |  |  |
| `timeout_days` | INTEGER | Yes | `15` |  |
| `source` | TEXT | Yes | `paper` |  |
| `setup_type` | TEXT | Yes |  |  |
| `setup_confidence` | REAL | Yes |  |  |
| `signal_entry_price` | REAL | Yes |  |  |
| `fill_entry_price` | REAL | Yes |  |  |
| `entry_slippage_bps` | REAL | Yes |  |  |
| `signal_exit_price` | REAL | Yes |  |  |
| `fill_exit_price` | REAL | Yes |  |  |
| `exit_slippage_bps` | REAL | Yes |  |  |
| `signal_price` | REAL | Yes |  |  |
| `fill_price` | REAL | Yes |  |  |
| `implementation_shortfall_bps` | REAL | Yes |  |  |
| `strategy_type` | TEXT | Yes | `pullback` |  |
| `actual_shares` | INTEGER | Yes |  |  |
| `exit_retry_count` | INTEGER | Yes | `0` | Tracks exit order retry attempts (max 3 before abandoning) |

**Indexes:** `idx_shadow_trades_status`, `idx_shadow_trades_ticker`, `idx_shadow_trades_recommendation_id`, `idx_shadow_trades_created_at`, `idx_shadow_trades_status_exit`

**Foreign Keys:** `recommendation_id` -> `recommendations.recommendation_id`

### `validation_results` | Sync: incremental

Preflight validation check results

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `result_id` | TEXT | **No** |  |  |
| `created_at` | TEXT | **No** |  |  |
| `overall_status` | TEXT | **No** |  |  |
| `checks_passed` | INTEGER | **No** |  |  |
| `checks_failed` | INTEGER | **No** |  |  |
| `checks_warning` | INTEGER | **No** |  |  |
| `results_json` | TEXT | **No** |  |  |


## Training Pipeline

### `audit_reports` | Sync: incremental

Periodic audit reports on model and system health

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `audit_id` | TEXT | **No** |  |  |
| `created_at` | TEXT | **No** |  |  |
| `audit_date` | TEXT | **No** |  |  |
| `overall_assessment` | TEXT | **No** |  |  |
| `summary` | TEXT | Yes |  |  |
| `flags` | TEXT | Yes |  |  |
| `metrics_to_watch` | TEXT | Yes |  |  |
| `model_health` | TEXT | Yes |  |  |
| `full_report` | TEXT | Yes |  |  |

### `canary_evaluations` | Sync: incremental

Canary eval runs to detect model quality degradation

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `eval_id` | TEXT | **No** |  |  |
| `created_at` | TEXT | **No** |  |  |
| `model_version` | TEXT | **No** |  |  |
| `avg_score` | REAL | Yes |  |  |
| `score_delta_pct` | REAL | Yes |  |  |
| `distinct_1` | REAL | Yes |  |  |
| `distinct_2` | REAL | Yes |  |  |
| `self_bleu` | REAL | Yes |  |  |
| `vocab_size` | INTEGER | Yes |  |  |
| `degradation_detected` | INTEGER | Yes | `0` |  |
| `details` | TEXT | Yes |  |  |

### `model_evaluations`

A/B comparisons between current and candidate models

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `evaluation_id` | TEXT | **No** |  |  |
| `created_at` | TEXT | **No** |  |  |
| `recommendation_id` | TEXT | Yes |  |  |
| `ticker` | TEXT | Yes |  |  |
| `input_text` | TEXT | **No** |  |  |
| `current_model` | TEXT | **No** |  |  |
| `current_output` | TEXT | Yes |  |  |
| `current_score` | REAL | Yes |  |  |
| `new_model` | TEXT | **No** |  |  |
| `new_output` | TEXT | Yes |  |  |
| `new_score` | REAL | Yes |  |  |
| `winner` | TEXT | Yes |  |  |
| `score_delta` | REAL | Yes |  |  |

### `model_versions` | Sync: full

Tracked model versions with training stats and holdout scores

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `version_id` | TEXT | **No** |  |  |
| `version_name` | TEXT | **No** |  |  |
| `created_at` | TEXT | **No** |  |  |
| `training_examples_count` | INTEGER | Yes |  |  |
| `synthetic_examples_count` | INTEGER | Yes |  |  |
| `outcome_examples_count` | INTEGER | Yes |  |  |
| `model_file_path` | TEXT | Yes |  |  |
| `status` | TEXT | **No** | `active` |  |
| `notes` | TEXT | Yes |  |  |
| `holdout_score` | REAL | Yes |  |  |
| `holdout_details` | TEXT | Yes |  |  |

### `preference_pairs`

DPO preference pairs for RLHF-style training

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `pair_id` | TEXT | **No** |  |  |
| `created_at` | TEXT | **No** |  |  |
| `ticker` | TEXT | Yes |  |  |
| `scan_date` | TEXT | Yes |  |  |
| `input_text` | TEXT | **No** |  |  |
| `chosen_output` | TEXT | **No** |  |  |
| `rejected_output` | TEXT | **No** |  |  |
| `chosen_source` | TEXT | Yes |  |  |
| `rejected_source` | TEXT | Yes |  |  |
| `quality_delta` | REAL | Yes |  |  |
| `notes` | TEXT | Yes |  |  |

### `quality_drift_metrics` | Sync: incremental

Training quality drift detection metrics per cycle

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `metric_id` | TEXT | **No** |  |  |
| `created_at` | TEXT | **No** |  |  |
| `cycle_number` | INTEGER | Yes |  |  |
| `model_version` | TEXT | Yes |  |  |
| `distinct_1` | REAL | Yes |  |  |
| `distinct_2` | REAL | Yes |  |  |
| `self_bleu` | REAL | Yes |  |  |
| `vocab_size` | INTEGER | Yes |  |  |
| `avg_length` | REAL | Yes |  |  |
| `degradation_flag` | INTEGER | Yes | `0` |  |
| `details` | TEXT | Yes |  |  |


## AI Council

### `council_debug_log` | Sync: incremental

Raw LLM request/response debug traces for council agents

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `debug_id` | TEXT | **No** |  |  |
| `session_id` | TEXT | **No** |  |  |
| `agent_name` | TEXT | **No** |  |  |
| `round` | INTEGER | **No** |  |  |
| `system_prompt_hash` | TEXT | Yes |  |  |
| `user_message` | TEXT | Yes |  |  |
| `raw_response` | TEXT | Yes |  |  |
| `parsed_successfully` | INTEGER | Yes | `0` |  |
| `parse_error` | TEXT | Yes |  |  |
| `latency_ms` | INTEGER | Yes |  |  |
| `created_at` | TEXT | **No** |  |  |

**Indexes:** `idx_council_debug_session`

**Foreign Keys:** `session_id` -> `council_sessions.session_id`

### `council_parameter_log` | Sync: incremental

Council-adjusted parameter changes with attribution windows

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `log_id` | TEXT | **No** |  |  |
| `session_id` | TEXT | **No** |  |  |
| `agent_name` | TEXT | Yes |  |  |
| `parameter_name` | TEXT | **No** |  |  |
| `default_value` | REAL | **No** |  |  |
| `council_value` | REAL | **No** |  |  |
| `applied_value` | REAL | **No** |  |  |
| `rate_limited` | INTEGER | Yes | `0` |  |
| `attribution_start` | TEXT | **No** |  |  |
| `attribution_end` | TEXT | Yes |  |  |
| `trades_during_window` | INTEGER | Yes | `0` |  |
| `pnl_during_window` | REAL | Yes |  |  |
| `counterfactual_pnl` | REAL | Yes |  |  |
| `value_added_dollars` | REAL | Yes |  |  |
| `created_at` | TEXT | **No** |  |  |

**Indexes:** `idx_param_log_session`, `idx_param_log_window`

### `council_parameter_state` | Sync: full

Current state of council-adjustable parameters

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `parameter_name` | TEXT | **No** |  |  |
| `current_value` | REAL | **No** |  |  |
| `default_value` | REAL | **No** |  |  |
| `last_session_id` | TEXT | Yes |  |  |
| `last_updated` | TEXT | **No** |  |  |

### `council_sessions` | Sync: incremental

Multi-agent council deliberation sessions

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `session_id` | TEXT | **No** |  |  |
| `session_type` | TEXT | **No** | `daily` |  |
| `trigger_reason` | TEXT | Yes |  |  |
| `created_at` | TEXT | **No** |  |  |
| `consensus` | TEXT | Yes |  |  |
| `confidence_weighted_score` | REAL | Yes |  |  |
| `is_contested` | INTEGER | Yes | `0` |  |
| `total_cost` | REAL | Yes |  |  |
| `rounds_completed` | INTEGER | Yes | `0` |  |
| `result_json` | TEXT | Yes |  |  |

**Indexes:** `idx_council_sessions_created`

### `council_votes` | Sync: incremental

Individual agent votes within council sessions

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `vote_id` | TEXT | **No** |  |  |
| `session_id` | TEXT | **No** |  |  |
| `agent_name` | TEXT | **No** |  |  |
| `round` | INTEGER | **No** |  |  |
| `position` | TEXT | Yes |  |  |
| `confidence` | INTEGER | Yes |  |  |
| `recommendation` | TEXT | Yes |  |  |
| `key_data_points` | TEXT | Yes |  |  |
| `risk_flags` | TEXT | Yes |  |  |
| `vote` | TEXT | Yes |  |  |
| `is_devils_advocate` | INTEGER | Yes | `0` |  |
| `direction` | TEXT | Yes |  |  |
| `confidence_float` | REAL | Yes |  |  |
| `assessment_json` | TEXT | Yes |  |  |

**Indexes:** `idx_council_votes_session`

**Foreign Keys:** `session_id` -> `council_sessions.session_id`


## Data Collection

### `analyst_estimates` | Sync: incremental

Analyst consensus estimates, price targets, and earnings surprises

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | **No** |  |  |
| `ticker` | TEXT | **No** |  |  |
| `date` | TEXT | **No** |  |  |
| `consensus_buy` | INTEGER | Yes |  |  |
| `consensus_hold` | INTEGER | Yes |  |  |
| `consensus_sell` | INTEGER | Yes |  |  |
| `consensus_strong_buy` | INTEGER | Yes |  |  |
| `consensus_strong_sell` | INTEGER | Yes |  |  |
| `price_target_high` | REAL | Yes |  |  |
| `price_target_low` | REAL | Yes |  |  |
| `price_target_mean` | REAL | Yes |  |  |
| `price_target_median` | REAL | Yes |  |  |
| `num_analysts` | INTEGER | Yes |  |  |
| `metric` | TEXT | Yes |  |  |
| `period` | TEXT | Yes |  |  |
| `estimate` | REAL | Yes |  |  |
| `actual` | REAL | Yes |  |  |
| `surprise` | REAL | Yes |  |  |
| `surprise_pct` | REAL | Yes |  |  |
| `source` | TEXT | Yes | `finnhub` |  |
| `collected_at` | TEXT | **No** |  |  |

**Indexes:** `idx_analyst_ticker_date`, `idx_analyst_unique`

### `cboe_ratios` | Sync: latest_only

CBOE equity/index put-call ratios

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | **No** |  |  |
| `collected_at` | TEXT | **No** |  |  |
| `collected_date` | TEXT | **No** |  |  |
| `equity_pc_ratio` | REAL | Yes |  |  |
| `index_pc_ratio` | REAL | Yes |  |  |
| `total_pc_ratio` | REAL | Yes |  |  |
| `equity_pc_vs_20d_avg` | REAL | Yes |  |  |

**Indexes:** `idx_cboe_ratios_date`

### `earnings_calendar` | Sync: incremental

Upcoming earnings dates for universe tickers

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | **No** |  |  |
| `ticker` | TEXT | **No** |  |  |
| `earnings_date` | TEXT | **No** |  |  |
| `earnings_time` | TEXT | Yes |  |  |
| `confirmed` | INTEGER | Yes | `0` |  |
| `collected_at` | TEXT | **No** |  |  |

### `edgar_filings` | Sync: incremental

SEC EDGAR filings with full text and sentiment analysis

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | **No** |  |  |
| `ticker` | TEXT | **No** |  |  |
| `cik` | TEXT | **No** |  |  |
| `form_type` | TEXT | **No** |  |  |
| `filing_date` | TEXT | **No** |  |  |
| `accession_number` | TEXT | **No** |  |  |
| `filing_url` | TEXT | Yes |  |  |
| `description` | TEXT | Yes |  |  |
| `full_text` | TEXT | Yes |  |  |
| `sections_json` | TEXT | Yes |  |  |
| `word_count` | INTEGER | Yes |  |  |
| `collected_at` | TEXT | **No** |  |  |
| `sentiment_polarity` | REAL | Yes |  |  |
| `sentiment_negative_count` | INTEGER | Yes |  |  |
| `sentiment_uncertainty_count` | INTEGER | Yes |  |  |
| `cautionary_phrases` | TEXT | Yes |  |  |
| `sentiment_delta_polarity` | REAL | Yes |  |  |

**Indexes:** `idx_edgar_ticker_date`, `idx_edgar_accession`

### `fed_communications` | Sync: incremental

Federal Reserve speeches, minutes, and press conferences

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | **No** |  |  |
| `comm_type` | TEXT | **No** |  |  |
| `title` | TEXT | Yes |  |  |
| `date` | TEXT | **No** |  |  |
| `speaker` | TEXT | Yes |  |  |
| `url` | TEXT | Yes |  |  |
| `full_text` | TEXT | Yes |  |  |
| `word_count` | INTEGER | Yes |  |  |
| `sentiment` | TEXT | Yes |  |  |
| `key_phrases` | TEXT | Yes |  |  |
| `source` | TEXT | Yes |  |  |
| `event_type` | TEXT | Yes |  |  |
| `event_date` | TEXT | Yes |  |  |
| `summary` | TEXT | Yes |  |  |
| `collected_at` | TEXT | **No** |  |  |

**Indexes:** `idx_fed_comm_type_date`, `idx_fed_unique`

### `google_trends` | Sync: latest_only

Google Trends search interest for tracked tickers

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | **No** |  |  |
| `collected_at` | TEXT | **No** |  |  |
| `collected_date` | TEXT | **No** |  |  |
| `ticker` | TEXT | **No** |  |  |
| `search_interest` | REAL | Yes |  |  |
| `interest_vs_90d_avg` | REAL | Yes |  |  |
| `spike_flag` | INTEGER | Yes |  |  |

**Indexes:** `idx_google_trends_ticker_date`

### `insider_transactions` | Sync: incremental

Insider buying/selling transactions from Finnhub

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | **No** |  |  |
| `ticker` | TEXT | **No** |  |  |
| `insider_name` | TEXT | Yes |  |  |
| `title` | TEXT | Yes |  |  |
| `transaction_type` | TEXT | Yes |  |  |
| `transaction_date` | TEXT | Yes |  |  |
| `filing_date` | TEXT | Yes |  |  |
| `shares` | REAL | Yes |  |  |
| `price` | REAL | Yes |  |  |
| `value` | REAL | Yes |  |  |
| `shares_after` | REAL | Yes |  |  |
| `ownership_type` | TEXT | Yes |  |  |
| `source` | TEXT | Yes | `finnhub` |  |
| `collected_at` | TEXT | **No** |  |  |

**Indexes:** `idx_insider_ticker_date`

### `macro_snapshots` | Sync: latest_only

FRED macroeconomic series snapshots

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | **No** |  |  |
| `collected_at` | TEXT | **No** |  |  |
| `collected_date` | TEXT | **No** |  |  |
| `series_id` | TEXT | **No** |  |  |
| `series_name` | TEXT | **No** |  |  |
| `value` | REAL | Yes |  |  |
| `previous_value` | REAL | Yes |  |  |
| `change_pct` | REAL | Yes |  |  |

**Indexes:** `idx_macro_snapshots_date`, `idx_macro_snapshots_series`

### `options_chains` | Sync: latest_only

Options chain snapshots with Greeks and volume data

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | **No** |  |  |
| `collected_at` | TEXT | **No** |  |  |
| `ticker` | TEXT | **No** |  |  |
| `expiration` | TEXT | **No** |  |  |
| `strike` | REAL | **No** |  |  |
| `option_type` | TEXT | **No** |  |  |
| `bid` | REAL | Yes |  |  |
| `ask` | REAL | Yes |  |  |
| `last_price` | REAL | Yes |  |  |
| `volume` | INTEGER | Yes |  |  |
| `open_interest` | INTEGER | Yes |  |  |
| `implied_volatility` | REAL | Yes |  |  |
| `delta` | REAL | Yes |  |  |
| `gamma` | REAL | Yes |  |  |
| `theta` | REAL | Yes |  |  |
| `vega` | REAL | Yes |  |  |
| `in_the_money` | INTEGER | Yes |  |  |
| `underlying_price` | REAL | Yes |  |  |

**Indexes:** `idx_options_chains_ticker_date`, `idx_options_chains_collected`, `idx_options_chains_expiration`

### `options_metrics` | Sync: latest_only

Derived options metrics: IV rank, put/call ratios, unusual activity

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | **No** |  |  |
| `collected_at` | TEXT | **No** |  |  |
| `collected_date` | TEXT | **No** |  |  |
| `ticker` | TEXT | **No** |  |  |
| `iv_rank` | REAL | Yes |  |  |
| `iv_percentile` | REAL | Yes |  |  |
| `put_call_volume_ratio` | REAL | Yes |  |  |
| `put_call_oi_ratio` | REAL | Yes |  |  |
| `atm_iv_30d` | REAL | Yes |  |  |
| `iv_skew` | REAL | Yes |  |  |
| `unusual_volume_flag` | INTEGER | Yes |  |  |
| `max_unusual_volume_ratio` | REAL | Yes |  |  |
| `total_call_volume` | INTEGER | Yes |  |  |
| `total_put_volume` | INTEGER | Yes |  |  |
| `total_call_oi` | INTEGER | Yes |  |  |
| `total_put_oi` | INTEGER | Yes |  |  |

**Indexes:** `idx_options_metrics_ticker_date`, `idx_options_metrics_date`

### `short_interest` | Sync: incremental

Short interest data with days-to-cover and float percentage

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | **No** |  |  |
| `ticker` | TEXT | **No** |  |  |
| `settlement_date` | TEXT | **No** |  |  |
| `short_interest` | REAL | Yes |  |  |
| `avg_daily_volume` | REAL | Yes |  |  |
| `days_to_cover` | REAL | Yes |  |  |
| `short_pct_float` | REAL | Yes |  |  |
| `source` | TEXT | Yes | `finnhub` |  |
| `collected_at` | TEXT | **No** |  |  |

**Indexes:** `idx_short_interest_ticker_date`, `idx_short_interest_unique`

### `vix_term_structure` | Sync: latest_only

VIX term structure snapshots across tenors

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | **No** |  |  |
| `collected_at` | TEXT | **No** |  |  |
| `collected_date` | TEXT | **No** |  |  |
| `vix` | REAL | Yes |  |  |
| `vix9d` | REAL | Yes |  |  |
| `vix3m` | REAL | Yes |  |  |
| `vix1y` | REAL | Yes |  |  |
| `term_structure_slope` | REAL | Yes |  |  |
| `near_term_ratio` | REAL | Yes |  |  |

**Indexes:** `idx_vix_ts_date`


## Research

### `research_digests` | Sync: incremental

Weekly research digest summaries

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | **No** |  |  |
| `week_start` | TEXT | **No** |  |  |
| `week_end` | TEXT | **No** |  |  |
| `papers_reviewed` | INTEGER | Yes |  |  |
| `actionable_count` | INTEGER | Yes |  |  |
| `digest_text` | TEXT | Yes |  |  |
| `threats` | TEXT | Yes |  |  |
| `opportunities` | TEXT | Yes |  |  |
| `created_at` | TEXT | **No** |  |  |

### `research_docs` | Sync: incremental

Uploaded research documents and reference materials

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | TEXT | **No** |  |  |
| `filename` | TEXT | **No** |  |  |
| `title` | TEXT | **No** |  |  |
| `category` | TEXT | **No** | `Uncategorized` |  |
| `content` | TEXT | **No** |  |  |
| `size_kb` | REAL | **No** | `0` |  |
| `updated_at` | TEXT | **No** |  |  |

### `research_papers` | Sync: incremental

Academic and industry research papers with relevance scoring

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | **No** |  |  |
| `source` | TEXT | **No** |  |  |
| `external_id` | TEXT | Yes |  |  |
| `title` | TEXT | **No** |  |  |
| `authors` | TEXT | Yes |  |  |
| `abstract` | TEXT | Yes |  |  |
| `url` | TEXT | **No** |  |  |
| `published_date` | TEXT | Yes |  |  |
| `categories` | TEXT | Yes |  |  |
| `relevance_score` | REAL | Yes |  |  |
| `relevance_reason` | TEXT | Yes |  |  |
| `full_text` | TEXT | Yes |  |  |
| `actionable` | INTEGER | Yes | `0` |  |
| `action_taken` | TEXT | Yes |  |  |
| `collected_at` | TEXT | **No** |  |  |


## Signals & Evaluation

### `build_score_history` | Sync: incremental

Daily composite build score with component breakdowns

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `score_id` | TEXT | **No** |  |  |
| `score_date` | TEXT | Yes |  |  |
| `build_score` | REAL | Yes |  |  |
| `gate_velocity` | REAL | Yes |  |  |
| `system_health` | REAL | Yes |  |  |
| `data_asset_value` | REAL | Yes |  |  |
| `model_quality` | REAL | Yes |  |  |
| `research_velocity` | REAL | Yes |  |  |
| `reliability` | REAL | Yes |  |  |
| `decay_applied` | INTEGER | Yes | `0` |  |
| `components_json` | TEXT | Yes |  |  |
| `created_at` | TEXT | Yes |  |  |

### `scan_metrics` | Sync: incremental

Per-scan pipeline metrics and throughput counters

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | **No** |  |  |
| `scan_number` | INTEGER | Yes |  |  |
| `scan_time` | TEXT | Yes |  |  |
| `universe_count` | INTEGER | Yes |  |  |
| `features_count` | INTEGER | Yes |  |  |
| `scored_count` | INTEGER | Yes |  |  |
| `packet_worthy` | INTEGER | Yes |  |  |
| `risk_passed` | INTEGER | Yes |  |  |
| `paper_traded` | INTEGER | Yes |  |  |
| `live_traded` | INTEGER | Yes |  |  |
| `llm_success` | INTEGER | Yes |  |  |
| `llm_total` | INTEGER | Yes |  |  |
| `llm_fallback` | INTEGER | Yes |  |  |
| `avg_conviction` | REAL | Yes |  |  |
| `duration_seconds` | REAL | Yes |  |  |
| `created_at` | TEXT | Yes |  |  |

### `schedule_metrics` | Sync: incremental

Daily schedule execution metrics

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | **No** |  |  |
| `metric_date` | TEXT | **No** |  |  |
| `metric_name` | TEXT | **No** |  |  |
| `metric_value` | REAL | Yes |  |  |
| `details` | TEXT | Yes |  |  |

### `setup_signals` | Sync: incremental

Technical setup signal detections with forward returns

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `signal_id` | TEXT | **No** |  |  |
| `created_at` | TEXT | **No** |  |  |
| `ticker` | TEXT | **No** |  |  |
| `date` | TEXT | **No** |  |  |
| `setup_type` | TEXT | **No** |  |  |
| `confidence` | REAL | Yes |  |  |
| `theoretical_entry` | REAL | Yes |  |  |
| `theoretical_stop` | REAL | Yes |  |  |
| `theoretical_target` | REAL | Yes |  |  |
| `regime` | TEXT | Yes |  |  |
| `adx` | REAL | Yes |  |  |
| `atr_ratio` | REAL | Yes |  |  |
| `rsi` | REAL | Yes |  |  |
| `volume_profile` | TEXT | Yes |  |  |
| `actual_return_1d` | REAL | Yes |  |  |
| `actual_return_5d` | REAL | Yes |  |  |
| `actual_return_10d` | REAL | Yes |  |  |
| `actual_return_20d` | REAL | Yes |  |  |
| `was_traded` | INTEGER | Yes | `0` |  |

### `traffic_light_state` | Sync: full

Market regime traffic light state machine

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | **No** |  |  |
| `current_regime` | TEXT | **No** | `GREEN` |  |
| `pending_regime` | TEXT | Yes |  |  |
| `pending_count` | INTEGER | Yes | `0` |  |
| `last_vix_score` | INTEGER | Yes | `0` |  |
| `last_trend_score` | INTEGER | Yes | `0` |  |
| `last_credit_score` | INTEGER | Yes | `0` |  |
| `last_total_score` | INTEGER | Yes | `0` |  |
| `updated_at` | TEXT | Yes |  |  |
| `last_transition_at` | TEXT | Yes |  |  |


## Infrastructure

### `activity_log` | Sync: incremental

System-wide event log for all notable actions

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | **No** |  |  |
| `event_type` | TEXT | **No** |  |  |
| `detail` | TEXT | Yes |  |  |
| `level` | TEXT | Yes |  |  |
| `created_at` | TEXT | **No** |  |  |

### `api_costs` | Sync: incremental

LLM API usage and cost tracking

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `cost_id` | TEXT | **No** |  |  |
| `created_at` | TEXT | **No** |  |  |
| `model` | TEXT | **No** |  |  |
| `purpose` | TEXT | **No** |  |  |
| `input_tokens` | INTEGER | **No** |  |  |
| `output_tokens` | INTEGER | **No** |  |  |
| `cost_dollars` | REAL | **No** |  | Legacy: was 'estimated_cost' in some modules |

### `command_results` | Sync: incremental

Results of remotely-issued commands

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `result_id` | TEXT | **No** |  |  |
| `command_id` | TEXT | **No** |  |  |
| `status` | TEXT | **No** |  |  |
| `result_json` | TEXT | Yes | `{}` |  |
| `error_message` | TEXT | Yes |  |  |
| `execution_ms` | INTEGER | Yes |  |  |
| `created_at` | TEXT | **No** |  |  |

### `config_overrides`

Dashboard-pushed configuration overrides (pulled from cloud)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `setting_key` | TEXT | **No** |  |  |
| `setting_value` | TEXT | **No** |  |  |
| `previous_value` | TEXT | Yes |  |  |
| `updated_at` | TEXT | **No** |  |  |
| `updated_by` | TEXT | Yes | `dashboard` |  |

### `council_calibrations` | Sync: incremental

Agent prediction calibration tracking

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `calibration_id` | TEXT | **No** |  |  |
| `session_id` | TEXT | **No** |  |  |
| `agent_name` | TEXT | **No** |  |  |
| `prediction` | TEXT | **No** |  |  |
| `prediction_confidence` | REAL | **No** |  |  |
| `verification_date` | TEXT | **No** |  |  |
| `actual_outcome` | TEXT | Yes |  |  |
| `correct` | INTEGER | Yes |  |  |
| `created_at` | TEXT | **No** |  |  |

**Indexes:** `idx_council_calibrations_session`

### `log_entries` | Sync: incremental

Structured log entries with source and severity

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `log_id` | TEXT | **No** |  |  |
| `log_level` | TEXT | **No** |  |  |
| `source` | TEXT | **No** |  |  |
| `message` | TEXT | **No** |  |  |
| `details_json` | TEXT | Yes |  |  |
| `created_at` | TEXT | **No** |  |  |

### `metric_snapshots` | Sync: incremental

Daily snapshots of key system metrics

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `snapshot_id` | TEXT | **No** |  |  |
| `created_at` | TEXT | **No** |  |  |
| `snapshot_date` | TEXT | **No** |  |  |
| `metrics_json` | TEXT | **No** |  |  |

### `pending_commands`

Remote commands queued for local execution (pulled from cloud)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `command_id` | TEXT | **No** |  |  |
| `command_type` | TEXT | **No** |  |  |
| `command_name` | TEXT | **No** |  |  |
| `payload_json` | TEXT | Yes | `{}` |  |
| `status` | TEXT | **No** | `pending` |  |
| `priority` | INTEGER | Yes | `0` |  |
| `created_at` | TEXT | **No** |  |  |
| `claimed_at` | TEXT | Yes |  |  |
| `expires_at` | TEXT | Yes |  |  |
| `created_by` | TEXT | Yes | `dashboard` |  |

### `sync_state`

Tracks last sync timestamp per table for incremental sync

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `table_name` | TEXT | **No** |  |  |
| `last_synced_at` | TEXT | **No** |  |  |

### `training_examples` | Sync: incremental

Curated instruction/output pairs for LLM fine-tuning

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `example_id` | TEXT | **No** |  |  |
| `created_at` | TEXT | **No** |  |  |
| `source` | TEXT | **No** |  |  |
| `ticker` | TEXT | Yes |  |  |
| `recommendation_id` | TEXT | Yes |  |  |
| `feature_snapshot` | TEXT | Yes |  |  |
| `trade_outcome` | TEXT | Yes |  |  |
| `instruction` | TEXT | **No** |  |  |
| `input_text` | TEXT | **No** |  |  |
| `output_text` | TEXT | **No** |  |  |
| `quality_score` | REAL | Yes |  |  |
| `difficulty` | TEXT | Yes |  |  |
| `curriculum_stage` | TEXT | Yes |  |  |
| `quality_score_auto` | REAL | Yes |  |  |
| `outcome_type` | TEXT | Yes |  |  |
| `regime` | TEXT | Yes |  |  |


## User Data

### `user_notes` | Sync: incremental

User-created notes with tags and pin support

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `note_id` | TEXT | **No** |  |  |
| `title` | TEXT | **No** |  |  |
| `content` | TEXT | Yes |  |  |
| `tags` | TEXT | Yes | `[]` |  |
| `pinned` | INTEGER | Yes | `0` |  |
| `created_at` | TEXT | **No** |  |  |
| `updated_at` | TEXT | **No** |  |  |
