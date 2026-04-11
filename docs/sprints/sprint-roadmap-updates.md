# Sprint: Roadmap & MASTER.md Updates — Post-Quarantine + LLM Authority Research

> **Branch:** `fix/roadmap-updates`
> **Priority:** MEDIUM — cosmetic + accuracy, not blocking trading
> **Estimated CC time:** 1–2 hours
>
> **Pre-flight:**
> ```bash
> git checkout main && git pull origin main
> git checkout -b fix/roadmap-updates
> cd frontend && npm run build && cd ..
> ```

---

## Context

After the April 10 cascade and quarantine, the roadmap and MASTER.md still show stale metrics (52 closed trades, Phase 1 gate passed). Real numbers: 18 verified trades, gate at 36%. Additionally, the LLM Authority Boundaries deep research produced new roadmap items and permanent architectural constraints. Six production hotfixes (v0.16.1–v0.16.6) have been merged but aren't reflected in the roadmap.

This sprint updates both the dashboard Roadmap page and MASTER.md Section 2 to reflect current reality.

---

## Task 1: Update MASTER.md Section 2 (volatile counts)

**File:** `MASTER.md`

Update the Key Metrics table (around line 55–65):

```markdown
| Metric | Value |
|---|---|
| Phase | 1 (Bootcamp) -- paper $100K + $100 live via Alpaca |
| Closed trades | 18 verified (77 quarantined from April 10 cascade) |
| Open positions | ~2 (verify with shadow-status) |
| Model | halcyon-v1.0.0 (Qwen3 8B, Q8_0 GGUF) |
| Training data | 1,019 examples (manual backfill pipeline ready, target 1,500) |
| Tests | 1,500+ functions across 123 test files |
| Python files | 212+ |
| Dashboard pages | 21 |
| Research docs | 66 |
| Sprint docs | 35 |
| Schema tables | 50 (registry), 44 synced to Postgres |
| GitHub issues | 0 open |
| Monthly cost | ~$64 (Render $14 + Ollama free + Claude API ~$50 + domain $7) |
| Hardware | RTX 3060 12GB, Windows 11, Z690, 24/7 operation |
```

Also update line 17 — the Release line:

```markdown
**Release:** v0.16.6 (6 hotfixes post-cascade: execution safety, quarantine, LLM quality, type coercion, Postgres drift, council weights)
```

**Do NOT touch** the Phase Gates section (Section 6, line ~488) — it already shows the correct "18 closed, 36%" numbers.

**Commit:** `docs(MASTER): update Section 2 — 18 verified trades, v0.16.6, training data 1,019`

---

## Task 2: Update Roadmap.jsx — metadata and Phase 1 description

**File:** `frontend/src/pages/Roadmap.jsx`

Update `ROADMAP_DATA` header:

```javascript
lastUpdated: '2026-04-11',
```

Update Phase 1 description:

```javascript
{ id: 'p1', name: 'Phase 1 — Bootcamp', status: 'active', capital: '$100K paper + $100 live', cost: '$64/mo', timeline: 'Apr–Jun 2026',
  desc: 'Prove the system has an edge. 18 verified closed trades post-quarantine (36% of 50-trade gate). Accumulating clean trades.',
```

**Commit:** `fix(roadmap): update last-updated date and Phase 1 description to post-quarantine reality`

---

## Task 3: Add new completed items to Phase 1

**File:** `frontend/src/pages/Roadmap.jsx`

Add to the `'Weeks 8–12: Risk & NLP'` subphase `items` array, BEFORE the `'Alpha attribution experiment'` item (which is `in-progress`). Place new `done` items before `in-progress` and `pending` items:

```javascript
{ l: 'Data quarantine system', s: 'done', c: 'ops', d: '77 compromised records flagged from April 10 cascade. 18 verified trades preserved ($604 P&L, 83% WR). All analytics queries filtered via COALESCE(quarantined, 0) = 0. Zero data deleted.', r: 'Data quality audit 2026-04-10' },
{ l: 'Execution safety hardening (12 fixes)', s: 'done', c: 'risk', d: 'Post-submit order verification, typed exception handling, duplicate position prevention, buying power failure alerts, exit_order_id tracking, cancel-before-close reconciliation. Prevents April 10 cascade repeat.', r: 'v0.16.0 trade rectification' },
{ l: 'LLM output quality gate', s: 'done', c: 'ai', d: 'repeat_penalty 1.15 suppresses degenerate repetition loops. Pre-parser rejects prompt leakage (37% of outputs), template stubs (10%), and repetition (14%) before XML parsing.', r: 'v0.16.4 hotfix #384' },
{ l: 'Write-boundary type coercion', s: 'done', c: 'ops', d: 'Systemic fix: _coerce_to_schema() converts dict values to match schema column types before INSERT/UPDATE. Root cause of 10+ prior TypeErrors across 8 subsystems.', r: 'v0.16.3 hotfix #383' },
{ l: 'LLM authority boundaries (FINSABER)', s: 'done', c: 'risk', d: 'Permanent exclusions defined: LLM never controls exits, sizing, or risk governor. Conviction soft multiplier only after 300+ calibrated trades. Validated by FINSABER (KDD 2026) — even GPT-4 fails at timing decisions.', r: 'LLM Authority Boundaries research' },
```

Add to the same subphase, in the `in-progress` / `pending` section:

```javascript
{ l: 'Manual backfill pipeline (regime-diverse)', s: 'in-progress', c: 'ai', d: 'Export 740 prompt files by regime (bull/bear/high-vol/range/recovery/PASS). Generate via Claude Opus + ChatGPT. Import with outcome pairing. Target: 500 new examples → 1,500 total dataset. ~$5 rubric scoring cost.', r: 'Manual backfill spec v4.0' },
{ l: 'Conviction calibration logging', s: 'pending', c: 'validation', d: 'Log conviction scores with zero gating power now. At 100 trades: compute Brier scores per decile. At 200: permutation test. At 300+: introduce ±15% soft multiplier if calibration confirmed. Never hard gate.', r: 'LLM Authority Boundaries: PolySwarm overconfidence finding' },
```

**Commit:** `feat(roadmap): add quarantine, execution safety, LLM quality, FINSABER items to Phase 1`

---

## Task 4: Add new items to Phase 2

**File:** `frontend/src/pages/Roadmap.jsx`

Add to Phase 2, `'Month 2: Scaling + risk'` subphase `items` array:

```javascript
{ l: 'Isolation Forest anomaly detection (CPU)', s: 'pending', c: 'risk', d: 'Portfolio-level anomaly detection on CPU (correlation, beta, sector concentration, P&L velocity). LLM explains flagged anomalies — never decides response. 97.69% accuracy in financial benchmarks. Contamination tuned to 0.02–0.03.', r: 'LLM Authority Boundaries: Tier 2, MIT Sloan circuit breaker research' },
{ l: 'FinBERT material event alerts', s: 'pending', c: 'data', d: 'Binary classifier for material events affecting open positions during market hours. Informational only — never auto-executes exits. Gate: <10% false positive rate over 30+ flagged events in shadow operation.', r: 'LLM Authority Boundaries: Tier 2, FinBERT >87% accuracy' },
{ l: 'Market regime narrative enrichment', s: 'pending', c: 'ai', d: 'LLM adds qualitative texture to deterministic Traffic Light regime classification. Traffic Light retains absolute authority over regime label. LLM commentary only — "narrow breadth despite ATH suggests elevated reversal risk."', r: 'LLM Authority Boundaries: Tier 2, FinBERT ensemble 73% improvement' },
```

**Commit:** `feat(roadmap): add Isolation Forest, FinBERT alerts, regime narrative to Phase 2`

---

## Task 5: Update Exit Management Framework

**File:** `frontend/src/pages/Roadmap.jsx`

Update `EXIT_FRAMEWORK` entries to reflect FINSABER findings:

```javascript
const EXIT_FRAMEWORK = [
  { phase: '1', trades: '18 → 50', strategy: 'Pure mechanical brackets', detail: 'Fixed stop at 2.0x ATR, fixed target. Log MFE/MAE for every trade. No discretion. FINSABER: LLM timing fails even at GPT-4 scale.', pct: 25, color: 'var(--arcis-accent)' },
  { phase: '2', trades: '50 → 200', strategy: 'Mechanical + rule-based', detail: 'Time-based stop tightening (2.0x → 1.5x by day 5). Signal exit: close > 5-day SMA. Still fully mechanical — no LLM input.', pct: 50, color: 'var(--chart-4)' },
  { phase: '3', trades: '200 → 500', strategy: 'Mechanical thesis rules', detail: 'Pre-specified thesis invalidation conditions at entry (mechanical, not LLM-driven). A/B test ATR-trailing vs fixed brackets. LLM provides post-trade commentary only.', pct: 75, color: 'var(--chart-1)' },
  { phase: '4', trades: '500+', strategy: 'Validated mechanical exits', detail: 'Deploy whichever mechanical exit rules won in walk-forward analysis. LLM commentary on exit quality for training data. No LLM exit execution — permanently excluded per FINSABER.', pct: 100, color: 'var(--chart-7)' },
]
```

**Key change:** Phase 3 no longer says "Evaluate LLM pilot" and Phase 4 no longer says "Full active... Full LLM exit management." FINSABER finding makes LLM-driven exits a permanent anti-recommendation.

**Commit:** `fix(roadmap): update exit framework — FINSABER permanently excludes LLM exit execution`

---

## Task 6: Frontend build verification

```bash
cd frontend && npm run build && cd ..
```

If the build fails, the JSX syntax has an error — fix before committing.

**No commit** — verification step only.

---

## Task 7: Final commit and push

```bash
git push origin fix/roadmap-updates
```

Then create PR:
```bash
curl -s -X POST "https://api.github.com/repos/millerrc18/halcyon-lab/pulls" \
  -H "Authorization: token YOUR_PAT" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "fix: roadmap + MASTER.md updates — post-quarantine metrics, FINSABER findings, 6 hotfixes",
    "body": "Updates roadmap and MASTER.md to reflect:\n- 18 verified trades (not 52) after April 10 quarantine\n- 5 new completed items (quarantine, execution safety, LLM quality, type coercion, FINSABER)\n- 2 new in-progress/pending Phase 1 items (manual backfill, conviction logging)\n- 3 new Phase 2 items (Isolation Forest, FinBERT, regime narrative)\n- Exit framework updated: FINSABER permanently excludes LLM exit execution\n- MASTER.md Section 2 corrected to v0.16.6 with real trade counts",
    "head": "fix/roadmap-updates",
    "base": "main"
  }'
```

---

## Verification Checklist

```bash
# Frontend builds
cd frontend && npm run build && cd ..

# MASTER.md has correct numbers
grep "Closed trades" MASTER.md  # should show "18 verified"
grep "v0.16.6" MASTER.md        # should appear in Release line

# Roadmap data is valid JS (no syntax errors caught by build)
# Visual check: open localhost:5173/roadmap after `npm run dev`

# No Python files changed — no pytest needed
```
