# Section 8 (Options Flow) source audit — closes #858

_Author: PM (rescue from terminated agent dispatch — agent surfaced the seed finding "options_collector.py → options_chains → options_metrics.py → options_metrics" before silent-terminating at 78s; PM completed the audit)._
_Date: 2026-04-29. Closes #858. Pre-Stage-1 robustness audit per operator's question on whether to do #858 first._

## TL;DR

**The PIT audit's working assumption (§A2.2: Section 8 has no live producer; treat as placeholder) is WRONG.**

There IS a live producer (`src/data_collection/options_metrics.py`), it writes to a PIT-capable schema (`options_metrics` table with `collected_at` + `collected_date` columns), and **3 of the 6 prompt-side fields ARE populated in production runtime**. But the loader (`src/features/engine_helpers.py::_load_options_metrics`) is **runtime-only** — `WHERE collected_at = (SELECT MAX(collected_at) FROM options_metrics)` — so historical decision points see the latest options data, not the as-of-date data.

Plus there's a **field-name mismatch** that silently breaks 1 of the 6 fields: prompt uses `iv_skew_25d`, loader writes `iv_skew`.

This means:
- **Pre-reg addendum 1 §A2.2 needs revision**: Section 8 is **PIT-broken**, not "no live producer / placeholder".
- **Phase 4 corpus generation as it stands** will run with 3 PIT-broken fields visible to the LLM — silently leaking future options data into historical decision points.
- This is a **must-fix-or-disable** before Stage 1 corpus generation.

## Audit methodology

Grep'd the 6 Section 8 field keys (`atm_iv_30d`, `iv_rank`, `iv_percentile`, `iv_skew_25d`, `put_call_vol_ratio`, `put_call_oi_ratio`) and `_interpret_skew` callers. Cross-referenced producer + schema + runtime loader. Read `src/llm/packet_writer.py:258-263` (the prompt section), `src/features/engine_helpers.py:52-81` (the loader), `src/data_collection/options_metrics.py` (the writer), `src/schema/registry.py:1043-1073` (the schema).

## Producer pipeline (CONFIRMED EXISTS)

```
src/data_collection/options_collector.py::collect_options_chains()
    → writes raw options chains to `options_chains` table

src/data_collection/options_metrics.py::compute_options_metrics()
    → reads `options_chains`
    → derives iv_rank, iv_percentile, put_call_volume_ratio,
       put_call_oi_ratio, atm_iv_30d, iv_skew, unusual_volume_flag
    → writes daily snapshots to `options_metrics` table

src/features/engine_helpers.py::_load_options_metrics()
    → reads `options_metrics`, returns dict per ticker
    → consumed by compute_all_features (and ultimately by packet_writer)
```

Drivers (the entry points that trigger writes):
- `src/cli/commands.py:1079-1102` — daily collection CLI
- `src/api/routes/actions.py:224-236` — on-demand collection API
- `src/commands/executor.py:124,131` — overnight execution

Both writes to `options_chains` and `options_metrics` are routine — the data is being collected daily.

## Schema — PIT-capable

`src/schema/registry.py:1043-1073`:

```python
TableDef(
    name="options_metrics",
    columns=[
        ColumnDef("id", "INTEGER", nullable=False),
        ColumnDef("collected_at", "TEXT", nullable=False),  # ← PIT-supporting
        ColumnDef("collected_date", "TEXT", nullable=False),  # ← PIT-supporting (date-only)
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("iv_rank", "REAL"),
        ColumnDef("iv_percentile", "REAL"),
        ColumnDef("put_call_volume_ratio", "REAL"),
        ColumnDef("put_call_oi_ratio", "REAL"),
        ColumnDef("atm_iv_30d", "REAL"),
        ColumnDef("iv_skew", "REAL"),
        ColumnDef("unusual_volume_flag", "INTEGER"),
        # ... + raw call/put volume + OI columns
    ],
    indexes=[
        IndexDef("idx_options_metrics_ticker_date", ["ticker", "collected_date"]),
        IndexDef("idx_options_metrics_date", ["collected_date"]),
    ],
    sync_to_postgres=True,
    sync_mode="latest_only",  # ← Render Postgres only carries latest snapshot
)
```

Two PIT timestamp columns + indexes by ticker+date. **The schema is PIT-clean.** A query like `WHERE ticker = ? AND collected_date <= as_of ORDER BY collected_date DESC LIMIT 1` would return the most recent options snapshot available at the historical decision point.

## Loader — RUNTIME-ONLY (the bug)

`src/features/engine_helpers.py:67-72`:

```python
rows = conn.execute(
    """SELECT ticker, iv_rank, put_call_volume_ratio, put_call_oi_ratio,
              iv_skew, unusual_volume_flag
       FROM options_metrics
       WHERE collected_at = (SELECT MAX(collected_at) FROM options_metrics)"""
).fetchall()
```

Three observations:

1. **No `as_of` parameter** — the loader has no way to express "what did this look like on YYYY-MM-DD". Every call returns the latest snapshot.
2. **`MAX(collected_at)` subquery is global** — even at runtime, this is a single timestamp across all tickers. A ticker with stale data (no recent collection) would be EXCLUDED from the result rather than returning its most recent record. This is a separate latent bug at runtime.
3. **Sub-selects only 5 of 11 useful columns** — drops `iv_percentile` and `atm_iv_30d` even though they're populated by the writer.

## Prompt-side mapping per field

| # | Prompt key | Loader returns it as | Schema column | Runtime status | Backtest status (corpus generator) |
|---|---|---|---|---|---|
| 1 | `iv_rank` | `iv_rank` | `iv_rank` | **populated, PIT-broken** | **PIT violation** |
| 2 | `iv_percentile` | _(not selected)_ | `iv_percentile` (exists) | renders 'n/a' | renders 'n/a' |
| 3 | `atm_iv_30d` | _(not selected)_ | `atm_iv_30d` (exists) | renders 'n/a' | renders 'n/a' |
| 4 | `iv_skew_25d` | loader returns `iv_skew` | `iv_skew` | **NAME MISMATCH** → renders 'n/a' | renders 'n/a' |
| 5 | `put_call_vol_ratio` | `put_call_vol_ratio` | `put_call_volume_ratio` | **populated, PIT-broken** | **PIT violation** |
| 6 | `put_call_oi_ratio` | `put_call_oi_ratio` | `put_call_oi_ratio` | **populated, PIT-broken** | **PIT violation** |

Field 4 is the most surprising — `iv_skew_25d` has been advertised in every LLM prompt for as long as the prompt has existed, **and has always rendered 'n/a'** because of a string-mismatch between loader and prompt. This also breaks the `_interpret_skew` helper at `src/llm/packet_writer.py:129` which reads `features.get('iv_skew_25d')` and returns 'n/a' on every call.

## Implications for Phase 4 corpus generation

The corpus generator (`src/evaluation/corpus_generator.py`, just landed in PR #876) calls `enrich_features(features, config, as_of=<decision_date>)` for each historical decision point. The PIT bundle (#854-#859) routes `as_of` through to news / fundamentals / insiders / macro / earnings — but **NOT through to options metrics**, because `_load_options_metrics` doesn't have an `as_of` parameter.

So today, if Phase 4 corpus generation runs:
- Sections 4, 5, 6, 7, 10 (fundamentals, insiders, news, macro, earnings) — **PIT-clean** ✓
- Section 8 (options) — **3 fields populated with `MAX(collected_at)` data** — silent future-data leak
- Section 11 (cross-asset) — **'n/a'** (no producer; matches addendum §A2.2)

The corpus's `prompt_section_omitted=(8, 11)` annotation per #96.2 is **WRONG for Section 8**: the section ISN'T omitted, it's contaminating the LLM's view with future data.

## Recommendations

The operator picks one of:

### Option A — Fix the loader (RECOMMENDED for Stage 1 robustness)
Add `as_of: str | None = None` to `_load_options_metrics`:

```python
def _load_options_metrics(as_of: str | None = None) -> dict[str, dict]:
    sql = """SELECT ticker, iv_rank, iv_percentile, put_call_volume_ratio,
                    put_call_oi_ratio, atm_iv_30d, iv_skew,
                    unusual_volume_flag
             FROM options_metrics
             WHERE (? IS NULL OR collected_date <= ?)
             AND collected_at = (
                 SELECT MAX(collected_at) FROM options_metrics
                 WHERE ticker = options_metrics.ticker
                 AND (? IS NULL OR collected_date <= ?)
             )"""
    # bind as_of four times
```

Plus:
- SELECT all 6 fields (currently missing `iv_percentile` + `atm_iv_30d`)
- Fix the field-name mapping for `iv_skew_25d` (rename loader return key OR rename prompt key OR add an alias)
- Plumb `as_of` through `enrich_features` (per-ticker loader split — current shape is global)
- Add tests mirroring the #855/#856/#857 PIT tests

Estimated 1 PR, ~half-day. Same shape as Phase 2 fixes.

**Pre-reg implication**: addendum-2 needed to update §A2.2 (Section 8 from "placeholder" to "fixed via #858 PR"). #870 Section 11 status unchanged.

### Option B — Drop Section 8 from corpus prompts (placeholder per addendum §A1.3)
Add Section 8 to corpus_generator's `_OMITTED_SECTIONS` list. Replace the section in the prompt with a constant placeholder string at the same character offset.

Pros: simple, no code surgery on the loader.
Cons: model has been trained on the runtime distribution (with 3 fields populated, 3 'n/a'). Replacing all 6 with placeholder text changes the inference distribution from training. Risky.

### Option C — Drop only Section 8 entries from corpus prompts (full omission)
Same as B but remove the section header entirely. Bigger inference-distribution change than B. Not recommended.

### Option D — Accept as-is, document in addendum-2
Run Stage 1 with Section 8 PIT-broken. Document the leak in addendum-2 + Stage 1 results. Caveat any analysis that uses options-flow signals.

Pros: zero engineering work.
Cons: the audit's whole reason for existing was to prevent this exact silent contamination. Accepting it after surfacing it would be a methodology drift.

## PM recommendation: Option A

The fix is mechanical (Phase 2 PIT pattern), the data is already being collected, the schema is already PIT-capable. The cost of doing it right is 1 PR (~half-day); the cost of doing it wrong is contaminating Stage 1 attribution analysis on every options-driven trade.

This is exactly the kind of robustness gap the operator's question ("review #858 first") was designed to catch.

## Pre-reg implications (operator decision)

If Option A: pre-reg addendum-2 needed before Stage 1 corpus generation. Updates §A2.2 — Section 8 reclassified as "fixed via #858 PR" and §A2.1 must-fix list extended.

If Option B/C/D: pre-reg addendum-2 needed before Stage 1 corpus generation. Updates §A2.2 — Section 8 reclassified from "placeholder/no-producer" to "PIT-broken-but-accepted" with rationale.

Either way, **addendum-2 is required before Phase 6 (Stage 1 backtest)** because the addendum-1 §A2.2 statement that Section 8 has no live producer is now known to be wrong.

## Strict-rigor receipts

- All 6 prompt fields traced from `_build_feature_prompt` to producer with file:line citations
- Schema inspected against actual registry definition (registry.py:1043-1073)
- Loader inspected against actual code (engine_helpers.py:67-72)
- Field-name mismatch on `iv_skew_25d` confirmed via grep — `iv_skew_25d` does not exist anywhere as a producer field, only as a consumer key in packet_writer.py
- Cross-referenced with PR #853 (PIT audit) §8 finding "Source not traced in #94 audit. Investigate the pipeline" — that finding is now resolved by this audit
- No code changes; doc-only deliverable
- PM-rescue from terminated agent: `arcis:design-codebase-analyst` opus terminated at 78s mid-investigation; PM completed using the agent's seed finding

## What this audit did NOT cover

- Did not inspect actual `options_metrics` table contents at `data/ai_research_desk.sqlite3` (would confirm coverage range + populated-vs-null rates per field). Worth doing during fix.
- Did not measure the Stage 1 contamination magnitude (how many trade decisions would actually flip if Section 8 became PIT-clean vs PIT-broken). Worth measuring once a fix lands, on a small smoke window.
- Did not check whether the Section 8 fields appear in any other code path beyond `_build_feature_prompt` + `_interpret_skew` + the ranker's IV-rank check. The ranker uses iv_rank for trade scoring — that's a runtime-only consumer (no historical backfill) so the bug is contained to the LLM prompt assembly path.
