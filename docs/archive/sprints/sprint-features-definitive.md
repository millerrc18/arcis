# Sprint: Research-Informed Features — Definitive Implementation Guide
# Version: 3.0 — Complete operational specification for Claude Code

> **This document is a sequence of exact operations. Execute them in order.**
> Every MODIFY operation specifies the exact text to find and the exact replacement.
> Every CREATE operation provides complete file contents.
> Do NOT paraphrase, interpret, or abbreviate. Execute verbatim.
>
> **STEP ZERO — CODEBASE REVIEW (before any code changes):**
> You have a large context window. Use it. Before writing a single line of code,
> read the following files IN FULL (not summaries, not grep — cat the entire file).
> Build a complete mental model of the scan pipeline flow, the risk governor
> checks, the enrichment chain, the watch loop orchestration, and the shadow
> trade lifecycle. Every integration point in this sprint connects to these files.
> If you find that the code has changed since this sprint was written (because
> another sprint landed first), ADAPT the operations to match the current code.
> The intent of each operation is more important than the exact text match.
>
> **Pre-read these files IN FULL before any code changes (mandatory):**
> ```
> cat AGENTS.md
> cat docs/research/The_Halcyon_Framework_v2__Multi-Strategy_Architecture_and_Operating_Playbook.md
> cat docs/research/Quantitative_Regime_Detection_for_Halcyon_Lab.md
> cat docs/research/AI_Council_Redesign__5-Agent_Strategic_Brain.md
> cat docs/research/PEAD_for_SP100__The_Drift_Evolved.md
> cat docs/research/REINFORCE_Plus_Plus_for_Financial_LLM_RL_on_Consumer_GPUs.md
> cat docs/research/Alpha_Decay_Detection_and_Strategy_Lifecycle_Management.md
> cat docs/roadmap-additions-2026-03-28.md
> cat src/services/scan_service.py
> cat src/risk/governor.py
> cat src/data_enrichment/enricher.py
> cat src/council/agents.py
> cat src/council/protocol.py
> cat src/council/engine.py
> cat src/llm/packet_writer.py
> cat src/shadow_trading/executor.py
> cat src/evaluation/hshs.py
> cat src/features/regime.py
> cat src/journal/store.py
> cat src/scheduler/watch.py
> cat frontend/src/App.jsx
> cat frontend/src/api.js
> cat frontend/src/pages/Council.jsx
> cat frontend/src/pages/Health.jsx
> cat frontend/src/pages/Dashboard.jsx
> cat src/api/cloud_app.py
> cat config/settings.example.yaml
> ```
>
> **Run before starting:** `python -m pytest tests/ -x -q` — ALL tests must pass.
> **Run after EACH Part:** `python -m pytest tests/ -x -q` — verify no regressions.
>
> **Research decisions (FINAL — do not deviate):**
> - Strategy #2 = Mean Reversion (Phase 2, Connors RSI(2), ρ = −0.35)
> - Strategy #3 = Evolved PEAD (Phase 3, composite earnings info system)
> - RL = Dr. GRPO (loss_type="dr_grpo" in TRL GRPOTrainer), skip DPO
> - Traffic Light = VIX + S&P 200-DMA + HY credit spread z-score
> - Council = vote-first, conditional Round 2, structured JSON output
> - PEAD enrichment = 5 earnings signals added to pullback prompt

---

# ══════════════════════════════════════════════════════════════
# PART 0: REMAINING RELIABILITY FIXES (4 operations)
# ══════════════════════════════════════════════════════════════

## OPERATION 0.1: Wire hshs.py into production

### Problem
`src/evaluation/hshs.py` has `compute_hshs_score(dimensions, months_active)` but:
1. It requires pre-computed dimension scores (0-100 each) — there is NO function that queries the database to compute those scores.
2. It is never called by any production code.

### Step 0.1.1: Create `src/evaluation/hshs_live.py` — the database wrapper

This new file queries the actual database to compute each HSHS dimension score, then calls `compute_hshs_score()` from the existing `hshs.py`.

**CREATE FILE `src/evaluation/hshs_live.py`:**

```python
"""Live HSHS computation from database state.

Queries the actual database to compute each HSHS dimension score (0-100),
then delegates to hshs.compute_hshs_score() for the weighted geometric mean.

This is the function production code should call. The pure
compute_hshs_score() in hshs.py is for testing/direct computation only.
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.evaluation.hshs import compute_hshs_score, DIMENSION_KEYS

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
DB_PATH = "ai_research_desk.sqlite3"

# System start date — used to compute months_active
SYSTEM_START = datetime(2026, 3, 25, tzinfo=ET)


def _score_performance(conn: sqlite3.Connection) -> float:
    """Score 0-100 for trading performance.

    Components:
    - Sharpe proxy (win rate * avg win / avg loss): 0-40 points
    - Win rate: 0-20 points
    - Max drawdown penalty: 0-20 points
    - Trade count (statistical significance): 0-20 points
    """
    score = 0.0

    closed = conn.execute(
        "SELECT pnl_pct, pnl_dollars FROM shadow_trades "
        "WHERE status = 'closed' AND pnl_pct IS NOT NULL"
    ).fetchall()

    if not closed:
        return 10.0  # Baseline score for no trades yet

    total = len(closed)
    wins = [r[0] for r in closed if r[0] and r[0] > 0]
    losses = [r[0] for r in closed if r[0] and r[0] < 0]

    # Win rate (0-20)
    win_rate = len(wins) / total if total > 0 else 0
    score += min(20, win_rate * 40)  # 50% WR = 20 pts

    # Profit factor proxy (0-40)
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 1
    pf = avg_win / avg_loss if avg_loss > 0 else 0
    score += min(40, pf * 20)  # PF 2.0 = 40 pts

    # Max drawdown penalty (0-20, starts at 20 and decreases)
    try:
        dd_row = conn.execute(
            "SELECT MAX(peak - equity) / MAX(peak) * 100 FROM "
            "(SELECT SUM(pnl_dollars) OVER (ORDER BY actual_exit_time) + 100000 as equity, "
            "MAX(SUM(pnl_dollars) OVER (ORDER BY actual_exit_time) + 100000) "
            "OVER (ORDER BY actual_exit_time) as peak "
            "FROM shadow_trades WHERE status = 'closed' AND actual_exit_time IS NOT NULL)"
        ).fetchone()
        dd_pct = dd_row[0] if dd_row and dd_row[0] else 0
        score += max(0, 20 - dd_pct)  # 0% DD = 20 pts, 20% DD = 0 pts
    except Exception:
        score += 10  # Default if computation fails

    # Trade count / statistical significance (0-20)
    if total >= 200:
        score += 20
    elif total >= 100:
        score += 15
    elif total >= 50:
        score += 10
    elif total >= 20:
        score += 5
    else:
        score += total * 0.25  # 0.25 pts per trade up to 20

    return min(100, max(0, score))


def _score_model_quality(conn: sqlite3.Connection) -> float:
    """Score 0-100 for LLM model quality.

    Components:
    - Template fallback rate (lower is better): 0-30 points
    - Average quality score of training examples: 0-30 points
    - Conviction calibration (conviction variance vs outcome): 0-20 points
    - Training data volume: 0-20 points
    """
    score = 0.0

    # Template fallback rate from recent scans (0-30)
    try:
        recent = conn.execute(
            "SELECT llm_success, llm_total FROM scan_metrics "
            "ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        if recent:
            total_llm = sum(r[1] for r in recent if r[1])
            success_llm = sum(r[0] for r in recent if r[0])
            if total_llm > 0:
                success_rate = success_llm / total_llm
                score += success_rate * 30  # 100% success = 30 pts
    except Exception:
        pass

    # Average quality score (0-30)
    try:
        avg_q = conn.execute(
            "SELECT AVG(quality_score) FROM training_examples "
            "WHERE quality_score IS NOT NULL AND quality_score > 0"
        ).fetchone()
        if avg_q and avg_q[0]:
            # Quality scores are 0-30 (sum of 6 dimensions × 0-5)
            # Normalize to 0-30 points
            score += min(30, (avg_q[0] / 30) * 30)
    except Exception:
        pass

    # Training data volume (0-20)
    try:
        count = conn.execute("SELECT COUNT(*) FROM training_examples").fetchone()
        if count:
            n = count[0]
            if n >= 2800:
                score += 20
            elif n >= 1000:
                score += 15
            elif n >= 500:
                score += 10
            else:
                score += (n / 500) * 10
    except Exception:
        pass

    # Conviction calibration placeholder (0-20) — needs enough closed trades
    score += 10  # Default mid-score until we have calibration data

    return min(100, max(0, score))


def _score_data_asset(conn: sqlite3.Connection) -> float:
    """Score 0-100 for data asset quality.

    Components:
    - Training examples count and growth: 0-25 points
    - Data freshness (most recent collection): 0-25 points
    - Source diversity: 0-25 points
    - Temporal coverage (days of operation): 0-25 points
    """
    score = 0.0

    # Training data volume (0-25)
    try:
        count = conn.execute("SELECT COUNT(*) FROM training_examples").fetchone()
        n = count[0] if count else 0
        score += min(25, (n / 2800) * 25)
    except Exception:
        pass

    # Data freshness — how recent is the latest collection? (0-25)
    try:
        tables = ["macro_snapshots", "insider_transactions", "edgar_filings",
                   "short_interest", "options_chains"]
        fresh_count = 0
        for table in tables:
            try:
                row = conn.execute(
                    f"SELECT MAX(created_at) FROM {table}"
                ).fetchone()
                if row and row[0]:
                    last = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                    if (datetime.now(ET) - last.replace(tzinfo=ET)).days <= 2:
                        fresh_count += 1
            except Exception:
                continue
        score += (fresh_count / max(1, len(tables))) * 25
    except Exception:
        pass

    # Source diversity (0-25) — how many different data sources populate the DB?
    try:
        sources = conn.execute(
            "SELECT COUNT(DISTINCT source) FROM training_examples WHERE source IS NOT NULL"
        ).fetchone()
        n_sources = sources[0] if sources else 0
        score += min(25, n_sources * 8)  # 3+ sources = 24 pts
    except Exception:
        pass

    # Temporal coverage (0-25)
    days_active = (datetime.now(ET) - SYSTEM_START).days
    score += min(25, (days_active / 365) * 25)  # 1 year = 25 pts

    return min(100, max(0, score))


def _score_flywheel_velocity(conn: sqlite3.Connection) -> float:
    """Score 0-100 for flywheel velocity.

    Components:
    - Retraining frequency (is Saturday retrain happening?): 0-25 points
    - Training data growth rate: 0-25 points
    - Model version count (iterations): 0-25 points
    - Closed trade → training example conversion rate: 0-25 points
    """
    score = 0.0

    # Model version count (0-25)
    try:
        versions = conn.execute(
            "SELECT COUNT(*) FROM model_versions"
        ).fetchone()
        n = versions[0] if versions else 0
        score += min(25, n * 5)  # 5+ versions = 25 pts
    except Exception:
        score += 5  # At least 1 version exists

    # Training data growth (new examples in last 30 days) (0-25)
    try:
        cutoff = (datetime.now(ET) - timedelta(days=30)).isoformat()
        recent = conn.execute(
            "SELECT COUNT(*) FROM training_examples WHERE created_at > ?",
            (cutoff,)
        ).fetchone()
        n = recent[0] if recent else 0
        score += min(25, (n / 100) * 25)  # 100 new in 30 days = 25 pts
    except Exception:
        pass

    # Remaining dimensions: default mid-scores
    score += 25  # Placeholder for retraining frequency + conversion rate

    return min(100, max(0, score))


def _score_defensibility(conn: sqlite3.Connection) -> float:
    """Score 0-100 for competitive defensibility.

    This is the hardest to measure automatically. Use proxies:
    - Proprietary data volume (can't be recreated): 0-30 points
    - System complexity (file count as proxy): 0-20 points
    - Integration depth (collectors, notifications, dashboards): 0-25 points
    - Time invested (days since start): 0-25 points
    """
    score = 0.0

    # Proprietary data (0-30)
    try:
        tables = ["training_examples", "shadow_trades", "scan_metrics",
                   "council_sessions", "macro_snapshots"]
        total_rows = 0
        for table in tables:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                total_rows += row[0] if row else 0
            except Exception:
                continue
        score += min(30, (total_rows / 10000) * 30)  # 10K rows = 30 pts
    except Exception:
        pass

    # System complexity — proxy for time investment (0-20)
    score += 15  # Static: we know we have 140+ files, 29K LOC

    # Integration depth (0-25)
    score += 15  # Static: 12 collectors, 29 notifications, 11 dashboard pages

    # Time invested (0-25)
    days_active = (datetime.now(ET) - SYSTEM_START).days
    score += min(25, (days_active / 365) * 25)

    return min(100, max(0, score))


def compute_hshs(db_path: str = DB_PATH) -> dict:
    """Compute the live Halcyon System Health Score from database state.

    This is the function production code should call.

    Returns:
        {
            "hshs": float (0-100),
            "dimensions": {
                "performance": float,
                "model_quality": float,
                "data_asset": float,
                "flywheel_velocity": float,
                "defensibility": float,
            },
            "weights": {dim: weight, ...},
            "phase": "early"|"growth"|"mature",
            "months_active": int,
            "computed_at": str (ISO),
        }
    """
    months_active = max(1, (datetime.now(ET) - SYSTEM_START).days // 30)

    try:
        with sqlite3.connect(db_path) as conn:
            dimensions = {
                "performance": _score_performance(conn),
                "model_quality": _score_model_quality(conn),
                "data_asset": _score_data_asset(conn),
                "flywheel_velocity": _score_flywheel_velocity(conn),
                "defensibility": _score_defensibility(conn),
            }
    except Exception as e:
        logger.error("[HSHS] Database query failed: %s", e)
        dimensions = {k: 0.0 for k in DIMENSION_KEYS}

    result = compute_hshs_score(dimensions, months_active)
    result["months_active"] = months_active
    result["computed_at"] = datetime.now(ET).isoformat()
    # Rename 'overall' to 'hshs' for API consistency
    result["hshs"] = result.pop("overall")

    logger.info(
        "[HSHS] Score=%.1f phase=%s P=%.0f M=%.0f D=%.0f F=%.0f C=%.0f",
        result["hshs"], result["phase"],
        dimensions["performance"], dimensions["model_quality"],
        dimensions["data_asset"], dimensions["flywheel_velocity"],
        dimensions["defensibility"],
    )

    return result
```

### Step 0.1.2: Add API endpoint

**MODIFY FILE `src/api/cloud_app.py`:**

Find the line:
```python
@app.get("/api/council/latest", dependencies=[Depends(verify_auth)])
```

Insert BEFORE it:
```python
@app.get("/api/health/hshs", dependencies=[Depends(verify_auth)])
def health_hshs():
    """Compute and return the live Halcyon System Health Score."""
    try:
        from src.evaluation.hshs_live import compute_hshs
        return compute_hshs()
    except Exception as e:
        logger.error("[API] HSHS computation failed: %s", e)
        return {"hshs": 0, "dimensions": {}, "error": str(e)}


```

### Step 0.1.3: Wire into CTO report

**MODIFY FILE `src/evaluation/cto_report.py`:**

Find the function that generates the report text. At the end (before the return statement), add:
```python
    # System Health Score (HSHS)
    try:
        from src.evaluation.hshs_live import compute_hshs
        hshs = compute_hshs()
        sections.append("\n## System Health Score (HSHS)")
        sections.append(f"Composite: {hshs.get('hshs', 0):.1f}/100 (phase: {hshs.get('phase', 'unknown')})")
        for dim, val in hshs.get("dimensions", {}).items():
            weight = hshs.get("weights", {}).get(dim, 0)
            sections.append(f"  {dim}: {val:.1f}/100 (weight: {weight:.0%})")
    except Exception as e:
        logger.warning("[CTO] HSHS computation failed: %s", e)
```

### Step 0.1.4: Wire into council shared context

**MODIFY FILE `src/council/protocol.py`:**

Find the exact text (the last try/except block in `build_shared_context`):
```python
    try:
        vix = _query_db(
```

Insert BEFORE that block:
```python
    try:
        from src.evaluation.hshs_live import compute_hshs
        hshs = compute_hshs()
        parts.append(f"System Health (HSHS): {hshs.get('hshs', 0):.1f}/100 "
                     f"(P={hshs['dimensions'].get('performance', 0):.0f} "
                     f"M={hshs['dimensions'].get('model_quality', 0):.0f} "
                     f"D={hshs['dimensions'].get('data_asset', 0):.0f} "
                     f"F={hshs['dimensions'].get('flywheel_velocity', 0):.0f} "
                     f"C={hshs['dimensions'].get('defensibility', 0):.0f})")
    except Exception as e:
        logger.warning("[COUNCIL] HSHS query failed: %s", e)

```

### Step 0.1.5: Add to frontend API

**MODIFY FILE `frontend/src/api.js`:**

Add at the end of the file (before any closing braces):
```javascript
export async function fetchHSHS() {
  return fetchApi('/health/hshs')
}
```

### Step 0.1.6: Create test file

**CREATE FILE `tests/test_hshs_live.py`:**

```python
"""Tests for src.evaluation.hshs_live."""

import sqlite3
import pytest
from datetime import datetime

from src.evaluation.hshs_live import compute_hshs, _score_performance


@pytest.fixture
def hshs_db(tmp_path):
    """Create a test database with minimal tables."""
    db = str(tmp_path / "test_hshs.sqlite3")
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE shadow_trades (
                trade_id TEXT PRIMARY KEY, status TEXT, pnl_pct REAL,
                pnl_dollars REAL, actual_exit_time TEXT, created_at TEXT, updated_at TEXT);
            CREATE TABLE training_examples (
                example_id TEXT PRIMARY KEY, source TEXT, quality_score REAL,
                created_at TEXT);
            CREATE TABLE scan_metrics (
                id INTEGER PRIMARY KEY, llm_success INTEGER, llm_total INTEGER,
                created_at TEXT);
            CREATE TABLE model_versions (
                version_id TEXT PRIMARY KEY, created_at TEXT);
            CREATE TABLE macro_snapshots (
                id INTEGER PRIMARY KEY, series_id TEXT, date TEXT, value REAL,
                created_at TEXT);
            CREATE TABLE council_sessions (
                session_id TEXT PRIMARY KEY, created_at TEXT);
        """)
    return db


class TestComputeHSHS:
    def test_returns_all_keys(self, hshs_db):
        result = compute_hshs(db_path=hshs_db)
        assert "hshs" in result
        assert "dimensions" in result
        assert "weights" in result
        assert "phase" in result
        assert "months_active" in result
        assert "computed_at" in result
        assert len(result["dimensions"]) == 5

    def test_empty_db_returns_nonzero(self, hshs_db):
        """Even with no data, some dimensions should have baseline scores."""
        result = compute_hshs(db_path=hshs_db)
        assert result["hshs"] >= 0
        assert result["phase"] == "early"

    def test_with_trades(self, hshs_db):
        """Performance score should increase with winning trades."""
        with sqlite3.connect(hshs_db) as conn:
            for i in range(10):
                conn.execute(
                    "INSERT INTO shadow_trades (trade_id, status, pnl_pct, pnl_dollars, actual_exit_time, created_at, updated_at) "
                    "VALUES (?, 'closed', ?, ?, ?, ?, ?)",
                    (f"t{i}", 2.0 if i < 7 else -1.0, 200 if i < 7 else -100,
                     datetime.utcnow().isoformat(), datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
                )
        result = compute_hshs(db_path=hshs_db)
        assert result["dimensions"]["performance"] > 10  # Better than baseline
```

---

## OPERATION 0.2: Consolidate overnight.py

**DELETE FILE:** `src/scheduler/overnight.py`
**DELETE FILE (if exists):** `tests/test_overnight.py`

**THEN:** Search for any imports of it and fix:
```bash
grep -rn "from src.scheduler.overnight" src/ scripts/ tests/ --include="*.py"
```
For each match: either delete the import line, or redirect to the equivalent function in `watch.py`.

---

## OPERATION 0.3: Fix notify_retrain_report placeholder values

**MODIFY FILE `src/scheduler/watch.py`:**

Find the exact text:
```python
                notify_retrain_report(
                    model_name=model_name,
                    training_examples=counts.get("total", 0),
                    prev_examples=counts.get("total", 0),
                    new_this_week=counts.get("total", 0),
                    new_paper=0,
```

Replace with:
```python
                # Compute accurate week-over-week training metrics
                _retrain_total = counts.get("total", 0)
                try:
                    import sqlite3 as _sq
                    from datetime import timedelta as _td
                    with _sq.connect("ai_research_desk.sqlite3") as _rc:
                        _week_ago = (datetime.now(ET) - _td(days=7)).isoformat()
                        _new_wk = _rc.execute(
                            "SELECT COUNT(*) FROM training_examples WHERE created_at > ?",
                            (_week_ago,)
                        ).fetchone()[0]
                        _new_paper = _rc.execute(
                            "SELECT COUNT(*) FROM training_examples WHERE created_at > ? AND source LIKE '%paper%'",
                            (_week_ago,)
                        ).fetchone()[0]
                except Exception:
                    _new_wk = 0
                    _new_paper = 0

                notify_retrain_report(
                    model_name=model_name,
                    training_examples=_retrain_total,
                    prev_examples=_retrain_total - _new_wk,
                    new_this_week=_new_wk,
                    new_paper=_new_paper,
```

---

## OPERATION 0.4: Separate live trade monitoring

**MODIFY FILE `src/shadow_trading/executor.py`:**

Find the function signature:
```python
def check_and_manage_open_trades(
```

Add parameter `source_filter`:
```python
def check_and_manage_open_trades(
    db_path: str = "ai_research_desk.sqlite3",
    source_filter: str | None = None,
) -> list[dict]:
```

Then find where open trades are queried (the call to `get_open_shadow_trades`). Add filtering:
```python
    open_trades = get_open_shadow_trades(db_path)
    if source_filter:
        open_trades = [t for t in open_trades if t.get("source") == source_filter]
```

**MODIFY FILE `src/scheduler/watch.py`:**

Find where `check_and_manage_open_trades` is called in the scan section. AFTER that call, add:
```python
            # Independent live trade check (fires even if paper trading disabled)
            try:
                from src.shadow_trading.executor import check_and_manage_open_trades as _check_live
                _live_actions = _check_live(source_filter="live")
                _live_closed = len([a for a in _live_actions if a.get("type") == "closed"])
                if _live_closed:
                    logger.info("[WATCH] Live trade check: %d trades closed", _live_closed)
            except Exception as e:
                logger.warning("[WATCH] Independent live trade check failed: %s", e)
```

---

# ══════════════════════════════════════════════════════════════
# PART 1: TRAFFIC LIGHT REGIME SYSTEM
# ══════════════════════════════════════════════════════════════

## OPERATION 1.1: Create the Traffic Light module

**CREATE FILE `src/features/traffic_light.py`:**

[The complete implementation from the previous expanded sprint — use the EXACT code from the `compute_traffic_light` function I wrote earlier, including all helper functions, persistence state management, and the full docstring. This is ~250 lines of working code that CC should copy verbatim.]

I have already written this complete module in the previous sprint draft. CC should read that draft file at `docs/sprints/sprint-features-expanded.md` and use the COMPLETE `traffic_light.py` implementation from Part 1A. It includes:
- `_classify_vix()`, `_classify_trend()`, `_classify_credit()` — each with exact thresholds from research
- `_get_credit_spread_stats()` — queries `macro_snapshots` for BAMLH0A0HYM2
- `_load_persistence_state()`, `_save_persistence_state()` — SQLite-backed state with CREATE TABLE
- `compute_traffic_light()` — full computation with persistence filter

---

## OPERATION 1.2: Wire Traffic Light into scan_service.py

**MODIFY FILE `src/services/scan_service.py`:**

Find EXACT text:
```python
    # Enrich features with fundamental, insider, and macro data
    try:
        from src.data_enrichment.enricher import enrich_features
        features = enrich_features(features, config)
    except Exception as e:
        logger.warning("[SCAN] Data enrichment failed: %s — continuing without enrichment", e)

    ranked = rank_universe(features)
```

Replace with:
```python
    # Enrich features with fundamental, insider, and macro data
    try:
        from src.data_enrichment.enricher import enrich_features
        features = enrich_features(features, config)
    except Exception as e:
        logger.warning("[SCAN] Data enrichment failed: %s — continuing without enrichment", e)

    # Traffic Light regime overlay — compute ONCE, apply to all tickers
    traffic_light = {"sizing_multiplier": 1.0, "total_score": -1, "regime_label": "unknown"}
    try:
        from src.features.traffic_light import compute_traffic_light
        vix_value = None
        # Use VIX from regime data if available (already computed in feature engine)
        for _t, _f in features.items():
            if "vix_proxy" in _f:
                vix_value = _f["vix_proxy"]
                break
        traffic_light = compute_traffic_light(spy, vix=vix_value)
        # Inject traffic light into every ticker's features
        for _t in features:
            features[_t]["traffic_light"] = traffic_light
            features[_t]["traffic_light_multiplier"] = traffic_light.get("sizing_multiplier", 1.0)
        logger.info(
            "[SCAN] Traffic Light: score=%d mult=%.1f regime=%s",
            traffic_light.get("total_score", -1),
            traffic_light.get("sizing_multiplier", 1.0),
            traffic_light.get("regime_label", "unknown"),
        )
    except Exception as e:
        logger.warning("[SCAN] Traffic Light computation failed: %s — using default (1.0)", e)
        for _t in features:
            features[_t]["traffic_light_multiplier"] = 1.0

    ranked = rank_universe(features)
```

---

## OPERATION 1.3: Wire Traffic Light into risk governor

**MODIFY FILE `src/risk/governor.py`:**

Find EXACT text:
```python
    def check_trade(self, ticker: str, allocation_dollars: float,
                    features: dict, portfolio: dict) -> dict:
```

Replace with:
```python
    def check_trade(self, ticker: str, allocation_dollars: float,
                    features: dict, portfolio: dict,
                    traffic_light_multiplier: float = 1.0) -> dict:
```

Find EXACT text (the first check in check_trade, right after `checks = []`):
```python
        if not self.enabled:
            return {"approved": True, "checks": [{"name": "governor_disabled", "passed": True, "detail": "Risk governor disabled"}]}

        # 1. Emergency halt
```

Replace with:
```python
        if not self.enabled:
            return {"approved": True, "checks": [{"name": "governor_disabled", "passed": True, "detail": "Risk governor disabled"}]}

        # 0. Traffic Light regime sizing override (applied BEFORE all other checks)
        if traffic_light_multiplier < 1.0:
            original_alloc = allocation_dollars
            allocation_dollars = allocation_dollars * traffic_light_multiplier
            checks.append({
                "name": "traffic_light",
                "passed": True,
                "detail": f"Traffic Light ×{traffic_light_multiplier:.1f}: "
                          f"${original_alloc:.0f} → ${allocation_dollars:.0f}",
            })
            logger.info("[RISK] Traffic Light applied: ×%.1f on %s ($%.0f → $%.0f)",
                        traffic_light_multiplier, ticker, original_alloc, allocation_dollars)

        # 1. Emergency halt
```

---

## OPERATION 1.4: Pass Traffic Light multiplier in executor

**MODIFY FILE `src/shadow_trading/executor.py`:**

Find EXACT text:
```python
        check = governor.check_trade(
            packet.ticker,
            packet.position_sizing.allocation_dollars,
            features,
            portfolio,
        )
```

Replace with:
```python
        tl_mult = features.get("traffic_light_multiplier", 1.0)
        check = governor.check_trade(
            packet.ticker,
            packet.position_sizing.allocation_dollars,
            features,
            portfolio,
            traffic_light_multiplier=tl_mult,
        )
```

---

## OPERATION 1.5: Create Traffic Light tests

**CREATE FILE `tests/test_traffic_light.py`:**

[Use the COMPLETE test file from the previous expanded sprint — it includes TestVIXClassifier, TestTrendClassifier, TestCreditClassifier, TestComputeTrafficLight with fixtures, persistence filter tests, and key coverage tests. ~120 lines.]

---

# ══════════════════════════════════════════════════════════════
# PART 2: PEAD ENRICHMENT FEATURES
# ══════════════════════════════════════════════════════════════

## OPERATION 2.1: Create earnings_signals.py

**CREATE FILE `src/data_enrichment/earnings_signals.py`:**

[Use the COMPLETE implementation from the previous expanded sprint — includes `compute_earnings_signals()` with all 5 signal computations, source queries from earnings_calendar and analyst_estimates tables. ~200 lines.]

---

## OPERATION 2.2: Wire into enricher.py

**MODIFY FILE `src/data_enrichment/enricher.py`:**

Find EXACT text:
```python
        enriched_count += 1

    logger.info(
        "[ENRICHMENT] Enriched %d/%d tickers (%d missing fundamentals, %d missing insider data)",
        enriched_count, total, missing_fundamentals, missing_insiders,
    )

    return features
```

Replace with:
```python
        # Earnings signals (PEAD enrichment for pullback adapter)
        try:
            from src.data_enrichment.earnings_signals import compute_earnings_signals
            earnings = compute_earnings_signals(ticker)
            feat["earnings_signals"] = earnings
            if earnings.get("include_in_prompt"):
                logger.debug("[ENRICHMENT] Earnings context included for %s (proximity: %s days, strength: %s)",
                             ticker, earnings.get("earnings_proximity_days"), earnings.get("earnings_signal_strength"))
        except Exception as e:
            feat["earnings_signals"] = {"include_in_prompt": False}
            logger.debug("[ENRICHMENT] Earnings signals failed for %s: %s", ticker, e)

        enriched_count += 1

    logger.info(
        "[ENRICHMENT] Enriched %d/%d tickers (%d missing fundamentals, %d missing insider data)",
        enriched_count, total, missing_fundamentals, missing_insiders,
    )

    return features
```

---

## OPERATION 2.3: Add earnings context to LLM prompt

**MODIFY FILE `src/llm/packet_writer.py`:**

Find EXACT text:
```python
    # SECTION 8: Entry/Stop/Targets
    prompt += f"""

=== TRADE PARAMETERS ===
```

Insert BEFORE that block:
```python
    # SECTION 7.7: Earnings Context (PEAD enrichment — conditional)
    earnings = features.get("earnings_signals", {})
    if earnings.get("include_in_prompt", False):
        earnings_lines = ["\n=== EARNINGS CONTEXT ==="]
        proximity = earnings.get("earnings_proximity_days")
        if proximity is not None:
            earnings_lines.append(f"Days to next earnings: {proximity}")
        surprise = earnings.get("last_surprise_pct")
        if surprise is not None:
            direction = earnings.get("last_surprise_direction", "unknown")
            earnings_lines.append(f"Last earnings surprise: {surprise:+.1f}% ({direction})")
        concordant = earnings.get("last_revenue_eps_concordant")
        if concordant is not None:
            earnings_lines.append(f"Revenue-EPS concordance: {'concordant' if concordant else 'mixed'}")
        rev_vel = earnings.get("analyst_revision_velocity_30d")
        if rev_vel is not None:
            trend_word = "rising" if rev_vel > 0 else "falling" if rev_vel < 0 else "stable"
            earnings_lines.append(f"Analyst revision trend (30d): {trend_word} ({rev_vel:+.1f}%)")
        inconsistent = earnings.get("recommendation_inconsistency")
        if inconsistent is not None:
            earnings_lines.append(f"Recommendation vs surprise: {'inconsistent (2.5-4.5x stronger signal)' if inconsistent else 'consistent'}")
        strength = earnings.get("earnings_signal_strength", "none")
        earnings_lines.append(f"Earnings signal strength: {strength}")
        prompt += "\n".join(earnings_lines)

```

---

## OPERATION 2.4: Create earnings signals tests

**CREATE FILE `tests/test_earnings_signals.py`:**

[Use the COMPLETE test file from the previous expanded sprint — includes earnings_db fixture, TestEarningsSignals class with beat detection, concordance, proximity trigger, and no-prompt-when-distant tests. ~80 lines.]

---

# ══════════════════════════════════════════════════════════════
# PART 3: IMPLEMENTATION SHORTFALL TRACKING
# ══════════════════════════════════════════════════════════════

## OPERATION 3.1: Add columns to shadow_trades

**MODIFY FILE `src/journal/store.py`:**

Find the end of the `initialize_database()` function (after all CREATE TABLE statements). Add:
```python
    # Implementation Shortfall tracking columns (safe ALTER — ignores if exists)
    for _alter in [
        "ALTER TABLE shadow_trades ADD COLUMN signal_price REAL",
        "ALTER TABLE shadow_trades ADD COLUMN implementation_shortfall_bps REAL",
    ]:
        try:
            conn.execute(_alter)
        except sqlite3.OperationalError:
            pass  # Column already exists
```

Also add the same ALTER statements to `_ensure_all_tables()` in `watch.py`.

## OPERATION 3.2: Capture signal price in scan pipeline

**MODIFY FILE `src/services/scan_service.py`:**

Find EXACT text:
```python
        packet = build_packet_from_features(ticker, feat, config)
```

Insert BEFORE it:
```python
        # Capture signal price for Implementation Shortfall tracking
        feat["signal_price"] = float(feat.get("current_price", 0))
```

## OPERATION 3.3: Store signal price in executor

**MODIFY FILE `src/shadow_trading/executor.py`:**

In `open_shadow_trade()`, AFTER the `insert_shadow_trade()` call (where trade_id is assigned), add:
```python
    # Store signal price for IS tracking
    signal_price = features.get("signal_price")
    if signal_price and trade_id:
        try:
            with sqlite3.connect(db_path) as _conn:
                _conn.execute(
                    "UPDATE shadow_trades SET signal_price = ? WHERE trade_id = ?",
                    (signal_price, trade_id),
                )
        except Exception as e:
            logger.warning("[IS] Failed to store signal price for %s: %s", packet.ticker, e)
```

In the section where the Alpaca fill price is received (after `actual_entry_price` is set), add IS computation:
```python
    # Compute Implementation Shortfall
    if signal_price and actual_entry_price and signal_price > 0:
        is_bps = ((actual_entry_price - signal_price) / signal_price) * 10000
        try:
            with sqlite3.connect(db_path) as _conn:
                _conn.execute(
                    "UPDATE shadow_trades SET implementation_shortfall_bps = ? WHERE trade_id = ?",
                    (round(is_bps, 2), trade_id),
                )
        except Exception as e:
            logger.warning("[IS] Failed to store IS for %s: %s", packet.ticker, e)

        # Rolling 20-trade IS alert
        if abs(is_bps) > 0:
            try:
                with sqlite3.connect(db_path) as _conn:
                    _avg = _conn.execute(
                        "SELECT AVG(implementation_shortfall_bps) FROM "
                        "(SELECT implementation_shortfall_bps FROM shadow_trades "
                        "WHERE implementation_shortfall_bps IS NOT NULL "
                        "ORDER BY created_at DESC LIMIT 20)"
                    ).fetchone()
                    if _avg and _avg[0] and _avg[0] > 10:
                        from src.notifications.telegram import send_telegram, is_telegram_enabled
                        if is_telegram_enabled():
                            send_telegram(
                                f"⚠️ Implementation Shortfall Alert\n"
                                f"Rolling 20-trade avg: {_avg[0]:.1f} bps (threshold: 10)\n"
                                f"Latest: {packet.ticker} = {is_bps:.1f} bps"
                            )
            except Exception as e:
                logger.warning("[IS] IS alert check failed: %s", e)
```

---

# ══════════════════════════════════════════════════════════════
# PART 4: AI COUNCIL REDESIGN — EXCLUDED FROM THIS SPRINT
# ══════════════════════════════════════════════════════════════

> **DO NOT implement council changes in this sprint.**
>
> The council redesign (vote-first protocol, structured JSON, 5 new agents,
> parameter auto-application, calibration tracking) is being designed and
> implemented separately through a collaborative architecture session.
> The changes to `src/council/agents.py`, `src/council/protocol.py`, and
> `src/council/engine.py` will be provided as a separate commit.
>
> **DO NOT modify any files in `src/council/`.**
>
> However, DO add the `council_calibrations` table to `_ensure_all_tables()`
> in watch.py so the schema is ready when the council redesign lands:

```sql
CREATE TABLE IF NOT EXISTS council_calibrations (
    calibration_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    agent_name TEXT,
    prediction TEXT NOT NULL,
    prediction_confidence REAL NOT NULL,
    verification_date TEXT NOT NULL,
    actual_outcome TEXT,
    correct INTEGER,
    created_at TEXT NOT NULL
);
```

Also add safe ALTER to council_sessions for the future result_json column:
```python
try:
    conn.execute("ALTER TABLE council_sessions ADD COLUMN result_json TEXT")
except sqlite3.OperationalError:
    pass  # Column already exists
```

---

# ══════════════════════════════════════════════════════════════
# PART 5: VALIDATION DASHBOARD PAGE
# ══════════════════════════════════════════════════════════════

The system validator backend exists (`src/evaluation/system_validator.py`) but the frontend page does NOT exist (`Validation.jsx` not found).

## OPERATION 5.1: Create Validation.jsx

**CREATE FILE `frontend/src/pages/Validation.jsx`:**

Build a React page that:
1. Fetches from `/api/system/validation` on load
2. Shows summary bar: X passed / Y warnings / Z failed with status badge
3. Groups checks by category (8 categories from the validator)
4. Each category is an expandable card showing individual checks
5. "Run Validation" button triggers fresh check
6. Shows last validation timestamp

Follow the exact component pattern from `Council.jsx` or `Training.jsx` (useEffect, useState, fetchApi pattern).

## OPERATION 5.2: Add route and navigation

**MODIFY FILE `frontend/src/App.jsx`:**

Find:
```jsx
                <Route path="/health" element={<Health />} />
```

Add after it:
```jsx
                <Route path="/validation" element={<Validation />} />
```

Add the import at the top:
```jsx
import Validation from './pages/Validation'
```

Add to navigation in Layout.jsx.

## OPERATION 5.3: Verify API endpoint

Ensure `/api/system/validation` exists in `cloud_app.py`. If not, add it following the pattern of other `/api/` routes.

---

# ══════════════════════════════════════════════════════════════
# PART 5B: NOTES PAGE (Cloud Dashboard)
# ══════════════════════════════════════════════════════════════

Ryan needs a simple notes tab on the cloud dashboard (halcyonlab.app) for
taking notes throughout the day. Persistent storage via the database.

## OPERATION 5B.1: Create notes table

**Add to `_ensure_all_tables()` in `src/scheduler/watch.py`:**
```sql
CREATE TABLE IF NOT EXISTS user_notes (
    note_id TEXT PRIMARY KEY,
    title TEXT,
    content TEXT NOT NULL,
    tags TEXT,
    pinned INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

Also add to `src/journal/store.py` `initialize_database()`.

## OPERATION 5B.2: Create API endpoints

**Add to `src/api/cloud_app.py`:**

```python
@app.get("/api/notes", dependencies=[Depends(verify_auth)])
def get_notes(limit: int = 50):
    """Get recent notes, pinned first."""
    try:
        rows = _query(
            "SELECT note_id, title, content, tags, pinned, created_at, updated_at "
            "FROM user_notes ORDER BY pinned DESC, updated_at DESC LIMIT ?",
            (limit,),
        )
        return {"notes": rows}
    except Exception as e:
        logger.error("[API] Notes fetch failed: %s", e)
        return {"notes": [], "error": str(e)}


@app.post("/api/notes", dependencies=[Depends(verify_auth)])
def create_note(payload: dict):
    """Create a new note."""
    import uuid
    from datetime import datetime
    note_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    title = payload.get("title", "")
    content = payload.get("content", "")
    tags = payload.get("tags", "")
    try:
        _execute(
            "INSERT INTO user_notes (note_id, title, content, tags, pinned, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 0, ?, ?)",
            (note_id, title, content, tags, now, now),
        )
        return {"note_id": note_id, "created_at": now}
    except Exception as e:
        logger.error("[API] Note create failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/notes/{note_id}", dependencies=[Depends(verify_auth)])
def update_note(note_id: str, payload: dict):
    """Update an existing note."""
    from datetime import datetime
    now = datetime.utcnow().isoformat()
    fields = []
    values = []
    for key in ("title", "content", "tags", "pinned"):
        if key in payload:
            fields.append(f"{key} = ?")
            values.append(payload[key])
    if not fields:
        return {"error": "No fields to update"}
    fields.append("updated_at = ?")
    values.append(now)
    values.append(note_id)
    try:
        _execute(f"UPDATE user_notes SET {', '.join(fields)} WHERE note_id = ?", tuple(values))
        return {"updated": True, "updated_at": now}
    except Exception as e:
        logger.error("[API] Note update failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/notes/{note_id}", dependencies=[Depends(verify_auth)])
def delete_note(note_id: str):
    """Delete a note."""
    try:
        _execute("DELETE FROM user_notes WHERE note_id = ?", (note_id,))
        return {"deleted": True}
    except Exception as e:
        logger.error("[API] Note delete failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
```

Also add `user_notes` to the Render sync table list in `src/sync/render_sync.py` so notes
sync from local to cloud AND from cloud back to local (bidirectional — notes created on the
cloud dashboard should sync back).

**Add to `scripts/render_migrate.py`:**
```sql
CREATE TABLE IF NOT EXISTS user_notes (
    note_id TEXT PRIMARY KEY,
    title TEXT,
    content TEXT NOT NULL,
    tags TEXT,
    pinned INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

## OPERATION 5B.3: Create frontend Notes page

**CREATE FILE `frontend/src/pages/Notes.jsx`:**

Build a React page that:
1. Fetches notes from `/api/notes` on load
2. Shows a list of notes on the left (or top on mobile), with pinned notes first
3. Shows a note editor on the right (or bottom on mobile)
4. "New Note" button creates a blank note
5. Auto-saves on blur or after 2 seconds of inactivity (debounced)
6. Each note has: title (editable), content (textarea or rich text), tags (comma-separated), pin toggle
7. Delete button with confirmation
8. Search/filter by tag or text content
9. Timestamps shown (created, last updated)
10. Mobile-friendly layout

**Style:** Match the existing dashboard dark theme (slate-800, slate-900 backgrounds, teal accents).
Use the same card pattern as other pages. Content area should use a monospace font for readability
(like JetBrains Mono — already imported in the dashboard).

**The textarea should be generous in size** — this is a note-taking tool, not a form field.
Minimum 300px height, resize vertically.

## OPERATION 5B.4: Add route, navigation, and API functions

**MODIFY `frontend/src/App.jsx`:**
```jsx
import Notes from './pages/Notes'
// Add route:
<Route path="/notes" element={<Notes />} />
```

**MODIFY `frontend/src/components/Layout.jsx`:**
Add "Notes" to the navigation menu with a 📝 icon.

**MODIFY `frontend/src/api.js`:**
```javascript
export async function fetchNotes(limit = 50) {
  return fetchApi(`/notes?limit=${limit}`)
}

export async function createNote(payload) {
  return fetchApi('/notes', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateNote(noteId, payload) {
  return fetchApi(`/notes/${noteId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteNote(noteId) {
  return fetchApi(`/notes/${noteId}`, {
    method: 'DELETE',
  })
}
```

---

# ══════════════════════════════════════════════════════════════
# PART 6: DOCUMENTATION (MANDATORY — DO NOT SKIP)
# ══════════════════════════════════════════════════════════════

## OPERATION 6.1: CHANGELOG.md

Add entries for:
1. Reliability sprint (already merged): all 3 criticals, 4 orphan modules wired, 12 Telegram notifications, 44+ silent exceptions
2. This sprint: Traffic Light, Council redesign, IS tracking, PEAD enrichment, HSHS wiring, Validation page, overnight consolidation

## OPERATION 6.2: docs/architecture.md

Update to include:
- `src/features/traffic_light.py` — Traffic Light regime overlay (3 indicators, persistence filter)
- `src/data_enrichment/earnings_signals.py` — PEAD enrichment features (5 signals)
- `src/evaluation/hshs_live.py` — Live HSHS computation from database state
- Updated council architecture (vote-first, structured JSON, calibration tracking)
- New tables: `traffic_light_state`, `council_calibrations`
- New columns: `shadow_trades.signal_price`, `shadow_trades.implementation_shortfall_bps`, `council_sessions.result_json`
- Deleted: `src/scheduler/overnight.py`, `src/shadow_trading/broker.py`

## OPERATION 6.3: AGENTS.md

Run these commands and update the counts in the comment at line 1:
```bash
echo "Python files:" && find src -name "*.py" ! -path "*__pycache__*" | wc -l
echo "LOC:" && find src -name "*.py" ! -path "*__pycache__*" -exec wc -l {} + | tail -1
echo "Tests:" && find tests -name "*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print s}'
echo "DB tables:" && grep -rn "CREATE TABLE" src/ scripts/ --include="*.py" | grep -v __pycache__ | sed 's/.*CREATE TABLE IF NOT EXISTS //;s/ (.*//' | sort -u | wc -l
echo "API routes:" && grep -c "@app\.\|@router\." src/api/cloud_app.py src/api/routes/*.py 2>/dev/null
echo "CLI commands:" && grep -c "add_parser" src/main.py
echo "Notifications:" && grep -c "^def notify_" src/notifications/telegram.py
echo "Research docs:" && ls docs/research/*.md | wc -l
```

## OPERATION 6.4: Roadmap updates

Update `docs/roadmap.md` with confirmed decisions:
- Strategy #2 = Mean Reversion (Phase 2)
- Strategy #3 = Evolved PEAD (Phase 3)
- RL = Dr. GRPO (loss_type="dr_grpo"), skip DPO
- Traffic Light built ✅
- PEAD enrichment features built ✅
- IS tracking built ✅
- Council redesigned ✅

## OPERATION 6.5: Research docs in dashboard

Add all 6 new research document filenames to the docs list in `src/api/routes/docs.py` and/or `src/data_collection/docs_collector.py`.

## OPERATION 6.6: Config updates

**MODIFY FILE `config/settings.example.yaml`:**

Add under `shadow_trading:`:
```yaml
execution:
  order_type: "market"           # "market" or "limit_at_ask"
  limit_timeout_seconds: 300     # Cancel unfilled limits after 5 minutes
```

## OPERATION 6.7: Final verification

```bash
python -m pytest tests/ -x -q
cd frontend && npm run build && cd ..
```

Both must pass. If any test fails, fix it before committing.

---

# ══════════════════════════════════════════════════════════════
# ACCEPTANCE CRITERIA CHECKLIST
# ══════════════════════════════════════════════════════════════

After completing all operations, verify each item:

- [ ] `python -c "from src.evaluation.hshs_live import compute_hshs; print(compute_hshs())"` — returns dict with hshs score
- [ ] `python -c "from src.features.traffic_light import compute_traffic_light; import pandas as pd; print('OK')"` — imports without error
- [ ] `python -c "from src.data_enrichment.earnings_signals import compute_earnings_signals; print('OK')"` — imports without error
- [ ] All 1,049+ tests pass (plus new tests added by this sprint)
- [ ] `npm run build` succeeds
- [ ] CHANGELOG.md has entries for both sprints
- [ ] AGENTS.md counts match code reality
- [ ] No remaining `except Exception: pass` blocks in modified files (use `grep -rn "except.*:$" src/ --include="*.py" -A1 | grep pass`)
- [ ] `overnight.py` deleted
- [ ] `broker.py` remains deleted (from prior sprint)
- [ ] Traffic Light `traffic_light_state` table created on first scan
- [ ] Council calibrations table created in `_ensure_all_tables()`
- [ ] council_sessions has `result_json` column (safe ALTER applied)
- [ ] shadow_trades has `signal_price` and `implementation_shortfall_bps` columns
- [ ] `src/council/agents.py` is UNCHANGED (council redesign handled separately)
- [ ] `src/council/protocol.py` is UNCHANGED
- [ ] `src/council/engine.py` is UNCHANGED
- [ ] Validation page exists at `/validation` route and renders

---

# Sprint Documentation Checklist (from docs/sprint-checklist.md)

### Tier 1 (MANDATORY):
- [ ] AGENTS.md — counts verified
- [ ] CHANGELOG.md — sprint entry
- [ ] docs/architecture.md — new modules/tables/endpoints
- [ ] README.md — verify still accurate

### Tier 2:
- [ ] config/settings.example.yaml — new keys
- [ ] frontend/src/api.js — new endpoints
- [ ] docs/roadmap.md — strategy decisions
