# Journal Schema v1

## Purpose
Capture every recommendation so the system can learn from outcomes, compare packet quality versus realized performance, and support future tuning.

## Table: recommendations

### Identity
- `recommendation_id` - unique ID
- `created_at` - timestamp ET
- `ticker`
- `company_name`
- `mode` - short_swing
- `setup_type`

### Scoring
- `priority_score` - internal rank score
- `confidence_score` - 1 to 10
- `packet_type` - morning_watchlist / action_packet / eod_recap_reference

### Market snapshot
- `price_at_recommendation`
- `market_regime`
- `sector_context`
- `trend_state`
- `relative_strength_state`
- `pullback_depth_pct`
- `atr`
- `volume_state`

### Packet fields
- `recommendation` - buy / watch / pass
- `thesis_text`
- `entry_zone`
- `stop_level`
- `target_1`
- `target_2`
- `expected_hold_period`
- `position_size_dollars`
- `position_size_pct`
- `estimated_dollar_risk`
- `reasons_to_trade`
- `reasons_to_pass`

### Event risk
- `earnings_date`
- `event_risk_flag` - none / earnings / other
- `hold_window_overlaps_earnings` - true / false
- `event_risk_warning_text`
- `conservative_sizing_applied` - true / false

### Workflow
- `packet_sent` - true / false
- `packet_sent_at`
- `ryan_approved` - true / false / null
- `ryan_executed` - true / false / null
- `ryan_notes`

### Shadow ledger
- `shadow_entry_price`
- `shadow_entry_time`
- `shadow_exit_price`
- `shadow_exit_time`
- `shadow_pnl_dollars`
- `shadow_pnl_pct`
- `max_favorable_excursion`
- `max_adverse_excursion`
- `shadow_duration_days`
- `thesis_success` - true / false / null

### Review
- `assistant_postmortem`
- `lesson_tag`
- `user_grade`
- `repeatable_setup` - true / false / null

## Review policy
Only trades Ryan actually executes require a full post-trade review from Ryan.
All recommendations still receive shadow-ledger outcome tracking.
