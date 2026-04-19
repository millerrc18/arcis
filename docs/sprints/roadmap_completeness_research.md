# Pass 2 — Roadmap completeness audit research (v0.25.2, #526)

**Branch:** `feat/roadmap-completeness-audit`
**Date:** 2026-04-19
**Scope:** Cross-reference Pass 1 evaluation against current codebase. Confirm issue state. Flag any surprise-shipped items. Flag stale issue details.

## Methodology

For each of the 20 items selected in Pass 1, three checks:

1. **Issue state**: `gh issue view <N> --json state,title,labels`
2. **Code provenance**: grep source tree for relevant identifiers
3. **Roadmap overlap**: check for existing items in `frontend/src/pages/Roadmap.jsx` that already cover the addition

## Issue verification matrix

| # | Item | Ref | Issue state | Code verification | Roadmap overlap |
|---|---|---|---|---|---|
| 1 | HSHS dashboard page | Memory | n/a | Health.jsx:247-289 ships both composite card + radar chart; `/api/health/hshs` live | None — not currently in Roadmap |
| 2 | AI Council 5→7 expansion | Memory | n/a | `src/api/routes/council.py:14` confirms 5 agents current; no scaffolding for 7 | Line 56 has "AI Council (5 agents)" done; expansion is net-new |
| 3 | Alpaca MCP server integration | Memory + repo URL | n/a | 0 integration files (3 doc-only mentions: MASTER.md, specs/, SYSTEM_STATE.md) | None |
| 4 | IB shadow broker mode (log-only) | Memory | n/a | IB shadow mode (dual routing) shipped; log-only variant distinct — 0 code mentions | Line 93 covers dual routing (done); log-only is net-new |
| 5 | ~~Research Analyst setup~~ | ~~Memory~~ | n/a | n/a | **SKIPPED** — Roadmap.jsx:161 explicitly supersedes |
| 6 | Refactor forensic_trade_audit_v1.py | #497 | OPEN | `scripts/diagnostics/forensic_trade_audit_v1.py` = 1,553 lines (issue says 1,534; +19 drift) | None |
| 7 | Repository pattern for SQLite | #478 | OPEN | 19 route files still directly access SQLite | None |
| 8 | Refactor executor.py mega-functions | #479 | OPEN | open_shadow_trade=565, check_and_manage_open_trades=618, open_live_trade=387 (matches 564/617/386 ±1) | None |
| 9 | shadow_trading test suite org | #480 | OPEN | `tests/` lacks `tests/shadow_trading/` subdirectory | None |
| 10 | WatchLoop god object | #367 | OPEN | `src/scheduler/watch.py` = 2,023 lines (issue says 2,003; +20 drift); class `WatchLoop` line 103 | None |
| 11 | Phase 0 manual unwind | #451 | OPEN | n/a — operator-owned action | None |
| 12 | Consolidate 4 position-cap sources | #432 | OPEN | position-cap logic in 4+ places: `exposure_limits.py`, `executor.py`, risk_governor, config | None |
| 13 | v0.24.1 scheduled-kind wiring | #494 | OPEN | `src/platform/signal_eval.py:180` — `NotImplementedError("scheduled-kind find_candidates_for_date not yet implemented")` | None |
| 14 | v0.24.1 python_plugin wiring | #493 | OPEN | `src/platform/signal_eval.py:188` — `NotImplementedError("python_plugin find_candidates_for_date is Task 2 (issue #474)")` | None |
| 15 | Tier 7: Factor decomposition + regime change detection | #492 | OPEN | Existing correlation_matrices + factor_loadings tables ship (Sprint 3) but Tier 7 specifically is additional | Line 120 covers Tier 1-3 stack (done); Tier 7 is net-new |
| 16 | Tier 7: Spearman correlation monitoring | #491 | OPEN | Spearman appears only in schema + exposure_limits.py (Tier 1-3); Tier 7 monitoring distinct | Line 120 covers Tier 1-3 (done); Tier 7 net-new |
| 17 | UPS purchase | Memory | n/a | 0 code mentions; "UPS" appears only in specs text for "Dedicated Arcis machine" | Line 177 mentions UPS in specs blurb; standalone purchase line is new |
| 18 | CPCV upgrade | Memory + research plan | n/a | 0 CPCV code files in `src/`; referenced only in research docs as future | None |
| 19 | Live walk-forward (rolling OOS) | Memory | n/a | Walk-forward v1 live (PR #520); live/rolling extension not built | Line 128 covers historical-only WF v1 (done); live variant distinct |
| 20 | v1.0.0 release gate | Forward versioning plan | n/a | Criteria in RELEASES.md but no Roadmap item | None |
| 21 | v0.27.x second strategy candidate | Forward versioning plan | n/a | 0 code (speculative spec stage) | Line 161 covers platform first tenant (Lazy Prices, in-progress); second-strategy candidate is next-tier |

## Findings

### Section 1 — HSHS surprise-ship (net-win)

HSHS is present and fully functional:
- **Backend:** `/api/health/hshs` endpoint (documented in `docs/dashboard-data-map.md:84`)
- **Frontend:** `Health.jsx:247-289` renders HSHS composite card + radar chart with 5 dimensions. `data-testid="hshs-composite"` + `data-testid="hshs-radar"` confirm dedicated panels.
- **CHANGELOG trail:**
  - v0.5.x era: "Added: HSHS radar chart and live phase-weight display on the Health page" (line 2329)
  - "HSHS live: 5-dimension health score from database, wired into CTO report + council + API" (line 2374)
  - v0.14.x: HSHS fixes referenced in MASTER.md line 267

**Resolution:** Ship as `s: 'done'` with `r: 'Health.jsx:247-289'`. Description should note that HSHS is a *section* of the Health page (not a separate page), clarifying the slight wording mismatch with the prompt.

### Section 2 — Research Analyst skip (guardrail #3)

The existing Phase 2 Month 2 item (`Roadmap.jsx:161`) explicitly retires this concept:

> "Supersedes the stale 'Research Analyst desk (relaxed thresholds)' concept — platform evaluates genuinely uncorrelated strategies, not relaxed variants of swing."

Memory reference for a "Research Analyst setup" is vague; concrete provenance in the Roadmap marks it as intentionally retired. Guardrail #3 (don't invent items when memory is vague) applies — skip.

### Section 3 — Issue-body drift (non-blocking)

Two line-count drifts surfaced:

1. **#497 `forensic_trade_audit_v1.py`**: issue says 1,534 lines; actual 1,553 (+19). Not invalidating — refactor scope unchanged.
2. **#367 WatchLoop**: issue says 2,003 lines; actual 2,023 (+20). Issue also claims "721-line run() method" but the class has been partially refactored via `HandlerRegistryMixin` (commit 8454fae). The `run()` method may have changed shape. Worth noting in the roadmap description: quote issue-body number with a caveat.

**Resolution for roadmap description:** Use current file sizes with issue reference; don't update issue bodies in this sprint (out of scope for additions-only work).

### Section 4 — Overlap check (no duplicates)

For each of the 20 items I plan to add, I grepped `Roadmap.jsx` for:
- Exact phrase match
- Partial phrase match (e.g., "Spearman", "CPCV", "v0.24.1", "executor.py", "WatchLoop", "Alpaca MCP", "position-cap", "UPS", "v1.0.0")

No duplicates found. The closest matches are substring mentions in existing items (e.g., "UPS" in the Dedicated Arcis machine specs blurb) which describe different scope than the standalone additions.

### Section 5 — v0.24.1 items: confirmation of pending state via raised exception

`src/platform/signal_eval.py:180-188` shows two `NotImplementedError` raises for exactly the scheduled-kind + python_plugin code paths:

```python
if kind == "scheduled":
    raise NotImplementedError(
        "[SIGNAL_EVAL] scheduled-kind find_candidates_for_date not yet implemented"
    )
if kind == "python_plugin":
    raise NotImplementedError(
        "python_plugin find_candidates_for_date is Task 2 (issue #474)"
    )
```

This is strong evidence — code explicitly signals the work as deferred. Both #493 and #494 belong in the parked subphase.

### Section 6 — No additional surprise-ships

I looked for intermediate ships on items 2-4, 6-21:

- **AI Council 7-agent**: No code scaffolding beyond the current 5-agent `src/council/agents.py`. No surprise ship.
- **Alpaca MCP**: 3 doc mentions, 0 integration. No surprise ship.
- **IB log-only**: 7 files match broadly ("shadow mode" references), but no dedicated log-only broker mode. No surprise ship.
- **executor.py mega-functions**: 3 mega-functions still measurable at claimed sizes. No surprise ship.
- **Repository pattern (#478)**: 19 API route files still directly call `sqlite3.connect()` / use `connect_db()`. No surprise ship.
- **Position-cap consolidation (#432)**: Multiple places still define caps. No surprise ship.
- **Tier 7 items (#491, #492)**: existing correlation monitoring is Tier 1-3 (Longin-Solnik + Carhart+QMJ). Tier 7 is an incremental addition. No surprise ship.
- **CPCV**: 0 code. No surprise ship.
- **Live walk-forward**: walk-forward v1 (#520) is historical-only. No rolling-OOS extension. No surprise ship.
- **UPS, v1.0.0 gate, v0.27.x candidate**: Pure planning items. No surprise ship possible.

## Category assignments

Per Roadmap.jsx `CAT` map (lines 12-21):

| # | Item | Category |
|---|---|---|
| 1 | HSHS dashboard page | `ops` |
| 2 | AI Council 5→7 | `ai` |
| 3 | Alpaca MCP | `ops` |
| 4 | IB log-only broker | `ops` |
| 6 | Refactor forensic_trade_audit_v1.py | `ops` |
| 7 | Repository pattern SQLite | `ops` |
| 8 | Refactor executor.py | `ops` |
| 9 | shadow_trading tests | `validation` |
| 10 | WatchLoop refactor | `ops` |
| 11 | Manual unwind residual shorts | `risk` |
| 12 | Consolidate position-cap sources | `risk` |
| 13 | v0.24.1 scheduled-kind wiring | `strategy` |
| 14 | v0.24.1 python_plugin wiring | `strategy` |
| 15 | Tier 7: Factor decomposition | `risk` |
| 16 | Tier 7: Spearman monitoring | `risk` |
| 17 | UPS purchase | `hardware` |
| 18 | CPCV upgrade | `validation` |
| 19 | Live walk-forward | `validation` |
| 20 | v1.0.0 release gate | `legal` |
| 21 | v0.27.x second strategy | `strategy` |

## Implementation plan for Pass 3

**Single-edit approach:** One Edit call per addition site.

1. **New Phase 1 subphase "Parked / deferred"**: single object with `label` + `items: [...]` array of 15 items. Insert after `v0.25.0 — Rigor + hygiene bundle` subphase (current line 137).

2. **Phase 2 Month 3 UPS**: append 1 item after "Dead man's switch" (line 178).

3. **Phase 3 new "Second strategy candidate (v0.27.x)" subphase**: single object, insert after "Months 3–6: Validation + scaling" subphase (line 205).

4. **Phase 5 Fund formation**: append 3 items (CPCV, live walk-forward, v1.0.0 gate) after "Seed capital conversations" (line 238).

5. **CHANGELOG [Unreleased]**: new "Changed" entry noting roadmap audit.

No MASTER.md changes required (prompt explicit). No code changes. Additions-only.

## Build/CI plan

After Pass 3 edits:
- `cd frontend && npm run build` — must pass (JSX syntax, data shape)
- `scripts/verify_docs.py` — must exit 0
- `scripts/run_ci_locally.ps1` — all green
- Paste summary in PR body per prompt

## Follow-up items (out of scope for this sprint)

- Issue #497 body: update line count 1,534 → 1,553 (separate sprint or single-line bump)
- Issue #367 body: update 2,003 → 2,023 and verify run() method length after HandlerRegistryMixin refactor
- Consider filing a Research Analyst setup "tombstone" comment pointing to the supersedence decision in Roadmap.jsx:161 if historical reference is valuable
