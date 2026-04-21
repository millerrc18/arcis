# Live-State Analysis — 2026-04-20

**Mode:** read-only, no state modifications. Kill-switch engaged.
**DB:** `C:/arcis/data/ai_research_desk.sqlite3` (read with `mode=ro&uri=true`).
**Alpaca:** paper account `460d9b3a-2932-4934-b532-34618d8c1c35`, base `https://paper-api.alpaca.markets`, read-only via `get_account_info` + `get_all_positions` + `get_orders(status=OPEN)`.

---

## 1. Executive summary

1. **16 broken-state trades confirmed.** 12 `needs_manual_review` are all net-short in Alpaca by exactly the quantity they were originally long — classic TP-plus-arcis-exit double-sell overshoot; two are *severe* (NVDA short 245 vs expected +49, GOOGL short 52 vs expected +13 — multiple overshoot cycles). 4 `exit_failed` are all stale (`source=live`, 2026-03-27 → 2026-04-01, all have zero or near-zero Alpaca footprint and were never cleaned up); AAPL is the worst — `stop_price=0`, `target_1=0`, `planned_shares=0`, live-sourced, sat broken for 24 days.
2. **3 additional latent issues surfaced in `status='open'` rows** (i.e. beyond the 16 specified): `SBUX` is a ghost (no Alpaca position), `CAT (2026-04-17, 2 shares)` has no alpaca_order_id and Alpaca has the ticker net-short -9 (but that short matches an older `needs_manual_review` CAT, so the 2-share open row is phantom), `TGT (2026-04-13, broker=ib, 76 shares)` can't be reconciled here because IB is dormant and Alpaca's TGT short -161 ties to the separate `needs_manual_review` TGT.
3. **Model registry is stale, not invalid.** DB has one row (`arcis:v1.0.0`, status=`rolled_back`); Ollama has `arcis:v1.0.0` loaded (8 days ago) + two older `halcyon` models; config's `llm.model: arcis:v1.0.0`. Ollama + config agree on `arcis:v1.0.0`. Functionally stable; governance record is lying.
4. **BP problem is structural.** Alpaca BP is $6,982.57 against $188,972.15 cash and $98,873.45 equity — the gap is entirely the 12 short positions consuming margin collateral. Today's 11 "Insufficient buying power" events match 11 AVGO `rejected_buying_power` rows in the journal; AVGO has zero Alpaca orders (blocked before submission). A cap reduction from 20 → 3 is **insufficient** in current state; the fix is reconciliation-first (close the 12 shorts), then BP recovers and the cap cut is either unnecessary or trivial.
5. **Urgency ranking for operator action:** 🔴 **Analysis 1** (#1 block for tomorrow's open — shorts accrue margin + slippage), 🟡 **Analysis 3** (blocked pipeline downstream; resolves largely from #1), 🟢 **Analysis 2** (stable in practice; one-row UPDATE to fix governance).

---

## 2. Analysis 1: Broken-state trades

**🔴 Urgent top flag — `AAPL` trade `1630b6c5-d7df-44f6-aca6-d0c4826ca697`:** entered 2026-03-27 at $253.69, `source=live`, `stop_price=0`, `target_1=0`, `target_2=0`, `planned_shares=0`. Has been in `exit_failed` for 24 days with the protective-default backfill (`stop = entry*0.95`, `target = entry*1.05` per CLAUDE.md) **never applied**. Alpaca has zero AAPL position and zero AAPL orders right now, so this is a pure DB phantom — safe to mark_orphan — but the fact that it sat with 0/0 stops for 24 days is the larger finding: the backfill protective-default path either didn't fire or was bypassed for this trade.

### Table — all 16 rows

Legend: `DB Alpaca?` column is the cross-reference result: **SHORT** = Alpaca has a short position of the expected magnitude (overshoot), **LONG** = position exists long, **NONE** = no Alpaca position for ticker. `Open orders?` checked separately via `get_orders(status=OPEN, symbols=[ticker])`.

| # | Ticker | Status | Entered | Shares | Entry $ | Stop | Target1 | Broker | Alpaca pos | Open orders | Classification |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | AAPL | exit_failed | 2026-03-27 | 0 | 253.69 | **0** | **0** | alpaca | NONE | NO | `MARK_ORPHAN` |
| 2 | WMT | exit_failed | 2026-04-01 | 1 | 124.28 | 121.73 | 129.39 | alpaca | LONG +92 (from 2026-04-13 `open` row) | YES (sell-limit 130.06 qty 92, from `open` row) | `MARK_ORPHAN` — this exit_failed row is stale; Alpaca's 92 shares belong to the 2026-04-13 `open` trade |
| 3 | CAT | exit_failed | 2026-04-01 | 1 | 731.86 | 708.10 | 779.38 | alpaca | SHORT -9 (from #7 below) | NO | `MARK_ORPHAN` — ambiguous; see CAT note below |
| 4 | CVX | exit_failed | 2026-04-01 | 1 | 199.10 | 194.17 | 208.95 | alpaca | SHORT -38 (from #5 below) | NO | `MARK_ORPHAN` — stale; Alpaca's -38 belongs to #5 |
| 5 | CVX | needs_manual_review | 2026-04-09 | 38 | 192.89 | 179.87 | 202.65 | alpaca | **SHORT -38** (exact overshoot) | NO | `CLOSE_AT_OPEN` (buy 38 to cover) |
| 6 | CAT | needs_manual_review | 2026-04-09 | 9 | 785.26 | 731.42 | 825.64 | alpaca | **SHORT -9** | NO | `CLOSE_AT_OPEN` (buy 9) |
| 7 | FDX | needs_manual_review | 2026-04-13 | 28 | 370.05 | 352.54 | 383.19 | alpaca | **SHORT -28** | NO | `CLOSE_AT_OPEN` (buy 28) |
| 8 | MO | needs_manual_review | 2026-04-13 | 169 | 67.33 | 64.41 | 69.52 | alpaca | **SHORT -169** | NO | `CLOSE_AT_OPEN` (buy 169) |
| 9 | GOOGL | needs_manual_review | 2026-04-13 | 13 | 317.62 | 299.97 | 330.85 | alpaca | **SHORT -52** (4× expected) | NO | `NEEDS_OPERATOR_JUDGMENT` — multiple overshoot cycles; 52 > 13 × 4; need to decide target qty |
| 10 | NVDA | needs_manual_review | 2026-04-13 | 49 | 188.16 | 178.17 | 195.65 | alpaca | **SHORT -245** (5× expected) | NO | `NEEDS_OPERATOR_JUDGMENT` — 5× overshoot; `market_value = -$49,416.50`, `unrealized_pl = -$1,212.86`; single largest stuck position |
| 11 | TGT | needs_manual_review | 2026-04-14 | 161 | 117.45 | 111.40 | 121.99 | **ib** | **SHORT -161 on Alpaca** (despite broker=ib) | NO | `NEEDS_OPERATOR_JUDGMENT` — broker field says IB (dormant) but Alpaca has the exact -161; either broker tag is wrong or TGT was migrated and not logged |
| 12 | BK | needs_manual_review | 2026-04-14 | 96 | 130.13 | 124.99 | 133.99 | alpaca | **SHORT -96** | NO | `CLOSE_AT_OPEN` (buy 96) |
| 13 | NEE | needs_manual_review | 2026-04-15 | 153 | 90.39 | 87.16 | 92.81 | alpaca | **SHORT -153** | NO | `CLOSE_AT_OPEN` (buy 153); overshoot recorded 2026-04-20 10:25 ET (today) |
| 14 | INTC | needs_manual_review | 2026-04-15 | 74 | 64.29 | 57.67 | 69.25 | alpaca | **SHORT -74** | NO | `CLOSE_AT_OPEN` (buy 74) |
| 15 | GM | needs_manual_review | 2026-04-15 | 216 | 78.18 | 73.69 | 81.55 | alpaca | **SHORT -216** | NO | `CLOSE_AT_OPEN` (buy 216) |
| 16 | GS | needs_manual_review | 2026-04-16 | 18 | 896.88 | 844.65 | 936.05 | alpaca | **SHORT -18** | NO | `CLOSE_AT_OPEN` (buy 18); overshoot recorded 2026-04-20 13:26 ET (today) |

### Per-trade narrative for non-trivial cases

**AAPL (#1):** see top flag. Operator decision: mark_orphan + close the DB row.

**WMT exit_failed (#2):** DB says `source=live, planned_shares=1` from 2026-04-01. Alpaca's current WMT position is +92 long at avg $125.40, which matches the **different** 2026-04-13 `open` row (same ticker, later entry, 92 planned). This exit_failed row is a dead ghost from the 2026-04-01 live-path era. Operator action: mark_orphan — do **not** close the Alpaca +92 position, it belongs to a still-healthy open trade with an active sell-limit.

**CAT exit_failed (#3) and needs_manual_review (#6):** Alpaca has exactly one CAT position, qty -9. The -9 matches the 2026-04-09 `needs_manual_review` row (#6, planned 9 long → overshoot to -9 short). The 2026-04-01 exit_failed row (#3, planned 1) is a separate dead trade from the live-path era — mark_orphan. **Additional wrinkle:** there is *also* a 2026-04-17 `open` CAT row with `planned_shares=2` and no `alpaca_order_id` (see "Additional open-row issues" below); it's a separate phantom.

**CVX exit_failed (#4) and needs_manual_review (#5):** same pattern as CAT. Alpaca's -38 short matches the 2026-04-09 needs_manual_review. The 2026-04-01 exit_failed is a dead live-path ghost — mark_orphan.

**GOOGL (#9):** Expected -13 (1× overshoot); Alpaca has -52 (4×). Hypothesis: reconciliation detected the first overshoot and set status to `needs_manual_review` on 2026-04-15, but the executor's exit path (before the cancel-before-close M1/M12 fixes land in Sprint 2) continued to fire `sell 13` on subsequent days, compounding. Operator decision: close all 52 (one `buy 52` market order), or split across multiple orders to manage slippage on a thin ticker day. Unrealized P&L -$361.75.

**NVDA (#10):** Expected -49; Alpaca has -245 (5×). Largest single stuck position. `market_value = -$49,416.50`, `unrealized_pl = -$1,212.86`. Same root cause as GOOGL but worse. Operator decision: close all 245 at open (likely market-buy, NVDA's liquidity supports it), or scale out over the session.

**TGT (#11):** `broker=ib` in DB, but Alpaca has TGT short -161 at avg $122.03 (exact magnitude match for #11's 161 planned shares). Two interpretations, both need operator: (a) the entry was actually routed via Alpaca but broker tag was mis-set to `ib` — in which case the fix is CLOSE_AT_OPEN on Alpaca for 161 and update the broker tag; (b) the entry was genuinely on IB and the Alpaca short is coincidentally the exact same magnitude from some other path — in which case close Alpaca but also chase the IB ghost (IB is currently dormant, ib-insync not installed). Since IB is dormant and Alpaca has the position, pragmatic path is (a). Flag to operator.

There is *also* a separate TGT `open` row from 2026-04-13 with `broker=ib, planned_shares=76` — not one of the 16, but worth flagging (see below).

### Additional open-row issues (not in the 16, but Alpaca cross-reference found them)

Three `status='open'` rows have stale/phantom Alpaca state:

| Ticker | DB status | Entered | Shares | Alpaca pos | Issue |
|---|---|---|---|---|---|
| **SBUX** | open | 2026-04-10 | 1 | **NONE** | Full phantom — no position, no orders. Operator: mark_orphan. |
| **CAT** | open | 2026-04-17 | 2 | SHORT -9 (belongs to row #6) | Phantom; no `alpaca_order_id`. Operator: mark_orphan, do not close the Alpaca -9 here (row #6 handles it). |
| **TGT** | open | 2026-04-13 | 76 (broker=ib) | SHORT -161 (belongs to row #11) | IB-tagged phantom. Operator: mark_orphan; IB is dormant so no IB cleanup possible from here. |

These three rows are not in the 16-item scope but will cause ongoing reconciliation mismatches if left. Including them pushes the true cleanup count to **19**.

### Classification counts

- `CLOSE_AT_OPEN`: 8 trades (CVX #5, CAT #6, FDX, MO, BK, NEE, INTC, GM) — straight buy-to-cover for the expected quantity each.
- `NEEDS_OPERATOR_JUDGMENT`: 3 trades (GOOGL 52, NVDA 245, TGT 161 with broker-tag ambiguity).
- `MARK_ORPHAN`: 4 exit_failed trades (AAPL, WMT-2026-04-01, CAT-2026-04-01, CVX-2026-04-01) + 3 open-row phantoms (SBUX, CAT-2026-04-17, TGT-2026-04-13) = 7 rows.
- `CANCEL_ORDERS` / `FIX_BRACKETS`: 0. No broken trade has orphan brackets that need cancelling — the overshoot pattern is "TP filled then Arcis sold again," so there are no pending legs to cancel on any of these 16.

---

## 3. Analysis 2: Model registry — three-way reconciliation

### DB — `model_versions`

Exactly **one row**:

```
version_id: b3866636-c189-4c7c-90aa-c44c097aa3de
version_name: arcis:v1.0.0
status:       rolled_back
created_at:   2026-03-25T18:36:30
training_examples_count: 790
model_file_path: training_data/halcyon-latest.gguf
```

`SELECT COUNT(*) WHERE status='active'` → **0**.

### Ollama — `ollama list`

```
arcis:v1.0.0             14f5b432cee8    8.7 GB    8 days ago
halcyon-v1.0.0:latest    7da5edeb0b58    8.7 GB    3 weeks ago
halcyonlatest:latest     7da5edeb0b58    8.7 GB    3 weeks ago
```

`ollama ps` → **nothing currently loaded into VRAM** (expected — VRAM handoff to overnight training ran at 18:50 ET; Ollama is idle until morning warm-up).

### Config — `config/settings.local.yaml:87`

```yaml
llm:
  model: arcis:v1.0.0
```

(Also `claude_model: claude-sonnet-4-20250514` at :108 for Claude fallback. Not the active inference model.)

### Three-way reconciliation

| Source | Current model | Status signal |
|---|---|---|
| DB `model_versions` | `arcis:v1.0.0` | `rolled_back` |
| Ollama `list` | `arcis:v1.0.0` (+ older halcyons as historical) | Loaded 8 days ago; no newer replacement |
| Config `llm.model` | `arcis:v1.0.0` | Active per config |

Ollama + config **agree**. DB **disagrees**. There is no newer model anywhere — no `arcis:v1.1.x`, no `halcyon:v2`, no ephemeral successor. The most plausible history: `arcis:v1.0.0` *was* rolled back at some point (perhaps after a canary failure during the weeks of training-pipeline breakage), then ended up as the operational model again without the status being flipped back.

Today's log shows 329 Ollama inferences against `arcis:v1.0.0` — the model is being queried successfully, so the system is functional on this model right now.

### Classification

- **`DB_STALE`** — Ollama + config agree on `arcis:v1.0.0`, DB's `rolled_back` status is the outdated one. Highest-probability classification.
- **Not `ROLLBACK_EXECUTED_NOT_RECORDED`** — a rollback-not-recorded scenario would show Ollama / config pointing at a prior model. They point at `arcis:v1.0.0`, not a predecessor.
- **Not `CONFIG_DRIFT`** — config agrees with Ollama.
- **Not `UNKNOWN_SUCCESSOR`** — there is no successor to identify; this is the model.

Caveat worth operator confirmation: if `arcis:v1.0.0` truly failed a canary/audit gate at some point and the rollback was deliberate, simply flipping DB to `status=active` reinstates a known-flawed model into the governance record. The question is not mechanical ("does the status match reality?") but editorial ("is `arcis:v1.0.0` what you want in production?").

---

## 4. Analysis 3: BP (buying power)

### Current Alpaca account state

```
cash:            $188,972.15
buying_power:    $6,982.57    <-- the pinch point
equity:          $98,873.45
portfolio_value: $98,873.45
status:          ACTIVE
```

The gap between cash and equity ($90K) is the **unrealized loss on the 12 short positions plus margin collateral**. Short positions tie up buying power as maintenance-margin collateral; the 12 shorts total approximately $188K notional, consuming roughly $282K of buying power at 150% margin (standard Reg T short). That's why cash is high but BP is thin.

### Today's BP rejections (from `logs/arcis.log`)

11 "Insufficient buying power" warnings on 2026-04-20, cadenced at the 30-min scan interval (10:44 → 15:50 ET):

```
10:44  need $15,970  have -$10,732  committed $37,942
11:15  need $15,940  have -$10,732  committed $37,942
11:46  need $15,537  have -$10,732  committed $37,942
12:16  need $15,477  have -$10,732  committed $37,942
12:47  need $15,526  have -$10,732  committed $37,942
13:18  need $15,506  have -$10,732  committed $37,942
13:48  need $15,469  have -$30,960  committed $37,942   <-- BP degraded further
14:21  need $15,473  have -$30,960  committed $37,942
14:52  need $15,477  have -$30,960  committed $37,942
15:21  need $15,555  have -$30,960  committed $37,942
15:50  need $15,565  have -$30,960  committed $37,942
```

Every one of these matches a DB row: 11 `shadow_trades` rows today with `ticker='AVGO', status='rejected', order_type='rejected_buying_power'`, share counts 39–40, entry prices $396.66–$399.26. Aligns perfectly — today's BP rejections are exclusively AVGO retries.

### AVGO-specific Alpaca check

- Open orders for AVGO: **0**
- Recent closed orders for AVGO: **0**

AVGO never reached the broker. The BP pre-flight check in `src/shadow_trading/executor.py:184` (`_check_paper_buying_power`) rejected every attempt before any order submission. There is no phantom AVGO state on Alpaca to clean up.

### BP check logic — location

`src/shadow_trading/executor.py:184` — `_check_paper_buying_power(entry_price: float, shares: int) -> bool`
```python
buying_power = float(acct.get("buying_power", 0))
effective_bp = buying_power - _scan_cycle_committed
# ... if required > effective_bp: return False
```

Invocation site: `executor.py:598` (inside `open_shadow_trade`), which is **after** the risk checks and **after** the LLM commentary generation (Ollama inference). Each AVGO rejection today therefore burned one full Ollama call (≈17s) + risk evaluation → 11 × ~17s = **~3 minutes of compute wasted** just rejecting AVGO for BP. Live-trading path (`open_live_trade`, line 1927) has a similar post-LLM BP check.

### Bootcamp cap

`config/settings.local.yaml:103` → `max_packets_per_scan: 20`
`config/settings.example.yaml:455` → `max_packets_per_scan: 8` (reference default)

### Arithmetic — does dropping cap to 3 resolve the rejections?

**Typical packet allocation**: the log shows "Drawdown 0.2% — risk scaled to 99% (alloc $15,741)" immediately preceding the BP rejections. So a single packet targets ~$15.5K at current drawdown-scaled risk.

**Current BP**: $6,982.57 (with 12 shorts consuming margin).
**BP with committed-cycle deducted**: effectively negative (`-$30,960`) because the 11 rejected cycles still count `committed_this_cycle = $37,942` (the committed-cycle counter isn't being released on rejection — separate executor bug flagged in the 2026-04-20 audit).

- Cap = 20 → want 20 × $15.5K = $310K allocation capacity; have $6.9K → **20× mismatch, predictable mass-rejection**.
- Cap = 3 → want 3 × $15.5K = $46.5K; have $6.9K → **6.7× mismatch, still mass-rejection**. Further degraded by the committed-cycle bug driving effective BP negative.
- Cap = 0 (no bootcamp) → no allocation needed; no rejections. But also no bootcamp packets, which isn't the system's intended state.

**After closing the 12 shorts** (reconciliation-first path):
- Released margin: ~$282K of short-maintenance collateral returns to BP.
- Cash outflow to close: ~$188K (buy to cover at current prices).
- **Net new BP**: roughly $6,982 + $282K − ($188K − released cash) ≈ $100K–$200K (order of magnitude; exact number depends on pricing at execution).
- Cap = 3 post-reconcile → 3 × $15.5K = $46.5K, fits comfortably.
- Cap = 20 post-reconcile → $310K, still exceeds post-reconcile BP; would need partial fills or cap still needs to drop.

### Classification

- Standalone, current state: **`CAP_REDUCTION_INSUFFICIENT`** — dropping 20 → 3 does not solve the rejections because the 12 shorts have already eaten the BP. Nothing downstream of the cap fixes this.
- Post-reconciliation: **`CAP_REDUCTION_SUFFICIENT`** — with BP recovered, cap=3 fits easily; cap=8 (the example default) would also fit.
- Parallel issue: **`NEEDS_PRE_FLIGHT_FIX`** — the BP check is at `executor.py:598` *after* LLM generation. Even when BP is healthy, a pre-LLM cheap BP check would prevent wasting Ollama inference on tickers that can't fund. Today's 11 AVGO retries each burned an Ollama inference that was predictably going to be rejected. Separately, the `committed_this_cycle` counter doesn't appear to be released on rejection (why effective BP went from -$10K to -$30K during the day without fills) — this is an independent executor bug (observed in the 2026-04-20 audit, not in Sprint 1 scope).

---

## 5. Operator decision menu

No recommendations — questions only.

### Analysis 1 (broken trades)

A. **For the 8 straightforward `CLOSE_AT_OPEN` cases (CVX 38, CAT 9, FDX 28, MO 169, BK 96, NEE 153, INTC 74, GM 216):** close all at market-open 09:30 ET, or stagger over the session, or limit-price? Each is a buy-to-cover of the exact overshoot quantity.

B. **For the 3 `NEEDS_OPERATOR_JUDGMENT` cases:**
   - **NVDA -245 (5× overshoot, $49K notional, -$1,213 unrealized):** market-buy all 245 at open, VWAP over session, or split across multiple smaller orders? Liquidity supports market-buy, but slippage on 245 NVDA at open could be meaningful.
   - **GOOGL -52 (4× overshoot):** same question at smaller scale.
   - **TGT -161 (broker-tag = IB but Alpaca has the position):** close on Alpaca and fix the broker tag, or investigate whether there's a separate IB ghost that needs chasing once IB is brought back online?

C. **For the 7 `MARK_ORPHAN` rows** (AAPL + the 3 2026-04-01 exit_failed + the 3 open-row phantoms SBUX / CAT-2026-04-17 / TGT-2026-04-13): status-update to `orphan` (or equivalent) in DB — do you want that via the normal `reconcile_all_paper_trades` (which needs C3 fixed first to run at all), a direct SQL UPDATE, or a dedicated one-off script?

D. **AAPL-specific:** do you want a root-cause investigation of why protective-default backfill didn't apply on 2026-03-27? That path sat with stop=0/target=0 for 24 days — either the backfill code didn't run, or it ran and no-op'd, or the trade was created by a path that bypasses backfill. This is a governance question distinct from cleanup.

E. **Scope question:** include the 3 additional open-row phantoms (SBUX / CAT-2026-04-17 / TGT-2026-04-13) in the Sprint-2 reconciliation pass, or handle them separately?

### Analysis 2 (model registry)

F. **Is `arcis:v1.0.0` actually the production model you want?** If yes, DB update to `status='active'` is a 1-query fix. If no, Ollama has `halcyon-v1.0.0:latest` (loaded 3 weeks ago) and `halcyonlatest:latest` as older candidates — do you want to revert config+Ollama+DB to one of those, or build a fresh model?

G. **If you do flip DB to `status='active'` for `arcis:v1.0.0`,** do you also want to add a `notes` entry explaining the round-trip (rolled_back → re-activated), or is a silent update acceptable?

H. **Independent of A1 fix:** do you want the rollback-audit path (who rolled it back, when, why) investigated, or is the current state sufficient context?

### Analysis 3 (BP)

I. **Sequencing:** reconciliation-first (close the 12 shorts, then BP recovers, then decide about cap) or cap-first (drop to 3 immediately as a hedge)? The arithmetic says cap-first alone doesn't help, but it doesn't hurt and costs nothing.

J. **Bootcamp cap level post-reconcile:** return to 20 (current), drop to 8 (example default), or something else? At 3-cap the system would under-utilize BP once shorts close; at 20 it risks re-running today's rejection pattern if any BP hiccup happens.

K. **Pre-flight BP check (executor.py:184 → :598):** move the BP check *before* LLM generation to save Ollama compute on unfundable tickers? This is code change, Sprint-2 candidate. Want it in scope?

L. **Committed-cycle counter release:** separately, the `_scan_cycle_committed = $37,942` appears to not be released on rejection (why effective BP went from -$10K to -$30K during the day). This is an independent executor bug. Want it in Sprint 2, or separate ticket?

M. **AVGO-specific:** today's 11 AVGO attempts all scored high enough to reach the BP check. Do you want the LLM/ranker to down-weight AVGO pre-score until BP recovers, or is the BP rejection the correct gate (even if inefficient)?

---

**ANALYSIS COMPLETE — report at docs/audit/live_state_analysis_2026-04-20.md. Awaiting operator decisions.**
