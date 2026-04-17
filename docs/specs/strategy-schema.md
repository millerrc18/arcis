# Strategy Spec Schema Reference

Strategy specs are YAML files consumed by `src.platform.strategy_spec`.
The canonical example is [`src/platform/specs/lazy_prices_v1.yaml`](../../src/platform/specs/lazy_prices_v1.yaml).

---

## Top-level keys

| Key | Required | Type | Description |
|-----|----------|------|-------------|
| `spec_version` | yes | int | Schema version. Currently always `1`. |
| `strategy_id` | yes | string | Unique machine ID. Must match filename (`lazy_prices_v1` → `lazy_prices_v1.yaml`). |
| `display_name` | yes | string | Human-readable label for reports/dashboards. |
| `description` | no | string | Multi-line description of strategy logic and hold period. |
| `citation` | no | string | Academic reference supporting the strategy. |

---

## `universe`

Dict. Defines the tradeable instrument set.

| Key | Type | Description |
|-----|------|-------------|
| `tickers` | string | Ticker universe. Currently only `"sp100"` is supported. |

---

## `entry`

Dict. Specifies how and when to open a position.

### `kind` (required)
One of: `scheduled`, `event_driven`, `python_plugin`.

#### `event_driven`
Triggers on a database event table (e.g. EDGAR filings).

| Key | Type | Description |
|-----|------|-------------|
| `event_table` | string | Source table (e.g. `edgar_filings`). |
| `event_filter.form_type` | list[str] | Form types to match (e.g. `[10-K, 10-Q]`). |
| `event_filter.filing_date_within_days` | int | Max days after filing to consider. |
| `signal` | list[dict] | Signal conditions. Each has `metric`, `target`, `reference`, `operator`, `threshold`. |
| `combinator` | string | `any` or `all` — how multiple signals combine. |

**Signal `operator` values:** `less_than`, `greater_than`, `equals`.

#### `scheduled`
Triggers on a calendar schedule. Additional keys TBD in future tasks.

#### `python_plugin`
Delegates entry to a Python callable. Additional keys TBD in future tasks.

---

## `exit`

Dict. Specifies how and when to close a position.

### `kind` (required)
One of: `mechanical`, `python_plugin`.

#### `mechanical`
Rule-based exit using time limit + ATR-based stop/target.

| Key | Type | Description |
|-----|------|-------------|
| `timeout_days` | int | Force-close after this many calendar days. |
| `stop` | dict | Stop-loss config (see ATR fields below). |
| `target` | dict | Profit-target config (see ATR fields below). |

**ATR stop/target fields:** `method` (`atr_based`), `atr_period`, `multiplier`, `floor_pct`, `cap_pct`.

#### `python_plugin`
Delegates exit to a Python callable. Additional keys TBD in future tasks.

---

## `position_sizing`

Dict. Controls capital allocation per trade.

| Key | Type | Description |
|-----|------|-------------|
| `method` | string | Currently only `fixed_pct_equity`. |
| `pct` | float | Fraction of equity per position (e.g. `0.15` = 15%). |
| `max_concurrent` | int | Maximum simultaneous open positions. |

---

## `attribution`

Dict. Configures performance measurement.

| Key | Type | Description |
|-----|------|-------------|
| `benchmark` | string | `SPY_matched_window` aligns SPY returns to each trade's exact hold window. |
| `metrics` | list[str] | Any of: `raw_sharpe`, `excess_sharpe`, `win_rate`, `profit_factor`, `max_drawdown`. |

---

## `llm_enhancement` (optional)

Dict. LLM-assisted signal extraction. Omit to disable.

| Key | Type | Description |
|-----|------|-------------|
| `enabled` | bool | Master switch. |
| `model` | string | Model identifier (e.g. `halcyon-v1.0.0`). |
| `role` | string | LLM task type (e.g. `structured_extraction`). |
| `prompt_template` | string | Key in the prompt registry. |
| `validation` | string | `verbatim_quote_grounded` requires evidence quotes in output. |

---

## Validation rules

Enforced by `src.platform.strategy_spec.validate_spec`:

- Required keys: `spec_version`, `strategy_id`, `display_name`, `universe`, `entry`, `exit`, `position_sizing`, `attribution`.
- `universe` must be a dict.
- `entry.kind` must be one of `event_driven`, `scheduled`, `python_plugin`.
- `exit.kind` must be one of `mechanical`, `python_plugin`.

Violations raise `ValueError` listing all errors.
