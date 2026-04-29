# Attribution coverage drop postmortem — closing #848

_Author: PM. Date: 2026-04-29. Closes #848._

## TL;DR

The "117 H1 vs 3 H2 LLM-taken trades" headline in `audits/attribution-readout-2026-04-28.md` §5 looked like a 39× coverage drop. **It's not a coverage drop — it's a model-version transition compounded with parse-failure pollution.** The bootcamp archive's H1/H2 time split is uninterpretable as "regime stability" because the two halves used **different models** with **different parse-failure rates**.

## Investigation

### Per-day take-rate breakdown

```
date       | total | taken | rejected | take rate
2026-04-06 |   260 |     0 |      260 |   0.0%
2026-04-07 |   320 |     0 |      240 |   0.0%
2026-04-08 |   269 |     0 |      260 |   0.0%
2026-04-09 |   267 |    16 |      244 |   6.0%
2026-04-10 |   135 |    75 |       45 |  55.6%   ← spike
2026-04-13 |   261 |    20 |      240 |   7.7%
2026-04-14 |   124 |     3 |      117 |   2.4%   ← back to baseline
2026-04-15 |   182 |     4 |      176 |   2.2%
2026-04-16 |   271 |     2 |      257 |   0.7%
…
2026-04-24 |   116 |     2 |      102 |   1.7%
```

This is **not** a clean H1/H2 split. The "H1 high" is driven entirely by Apr 09 + Apr 10 + Apr 13. Apr 14 already shows the post-transition baseline.

### What was different about Apr 09-10?

Conviction value distribution for `llm_action='taken'` rows:

```
date       | conviction=5 | other (1, 7, 8, 9) | conviction=5 share
2026-04-09 |          14  |                  2 |  87.5%
2026-04-10 |          63  |                 12 |  84.0%
2026-04-13 |           0  |                 20 |   0.0%
```

**77 of 91 Apr 09-10 takes are conviction=5** — the parser's parse-failure fallback per `src/llm/packet_writer.py:692,701,710`. These aren't real LLM-confidence-5 takes. They're **parse-failures masquerading as takes**.

### What changed between Apr 10 and Apr 13?

Model version per day (from `recommendations.model_version`):

```
date       | model
2026-04-06 → 04-10 | halcyon-v1.0.0
2026-04-13 onward  | arcis:v1.0.0       ← transition
```

The model was renamed/replaced between Apr 11-12 (weekend window with no scans). The transition coincides with the parse-failure rate dropping from ~85% on takes to 0%. Either:
- The new model produces cleanly-parseable responses where the old one didn't, OR
- A parser change between Apr 11-13 better matched the new model's output format

The git log around that window shows multiple test/dependency hotfixes but no clear "model swap" commit. The version-string change in the data is itself the smoking gun.

## What this means

### The audit's §5 H1/H2 replication is uninterpretable

§5 of `attribution-readout-2026-04-28.md` reports:

```
            first half     second half
n_taken        117             3
n_rejected    1542           296
delta         0.4838        0.7619
p_value       0.1292        0.6987
```

The H1 result is dominated by **parse-failure rows under halcyon-v1.0.0**, not real LLM decisions.
The H2 result is **arcis:v1.0.0 with N=3** (statistical noise).

Comparing them tests neither time stability nor regime robustness — it's an apples-to-oranges comparison of "old model parse failures" to "new model real takes."

### The headline §4 t-test (delta=+0.27%, p=0.40) is also affected

Of the 120 §4 `taken` rows, 77 are conviction=5 (likely parse-failure pollution from Apr 09-10 under old model). If those are removed, the §4 effective N drops to ~43 with a different mean. The directional signal (positive delta) may persist but the magnitude is uncertain until #850 separates real-medium from parse-failure.

## Recommendations

### Before re-running attribution_readout

1. Land #850 (parse-failure NULL semantics or parse-failed flag) so conviction=5 can be cleanly partitioned.
2. Re-run on a window containing only ONE model version (Apr 13 onward — `arcis:v1.0.0`).
3. The §5 time-split inside that window may surface a real regime effect or confirm stability — but only after #850.

### For Stage 1 walk-forward backtest (#83)

The Stage 1 corpus pre-computation (Phase 4) must:
- Use **one model version throughout** the entire walk-forward window
- Include **per-decision parse-failure tagging** so audit-time partitioning is possible
- Tag each LLM response with the parser strategy that succeeded (which of the 7 fallbacks fired) for diagnostic transparency

This is consistent with the Phase 3 pre-reg addendum scope (#95).

### For the original §5 hypothesis ("did something break around Apr 15")

Closed as **mistaken hypothesis**. The pattern in the data is:
- 2026-04-06 → 04-08: ramp-up phase (0 takes — possibly initial calibration)
- 2026-04-09 → 04-10: parse-failure spike under halcyon-v1.0.0 (false-positive takes)
- 2026-04-13: model transition to arcis:v1.0.0
- 2026-04-13 onward: stable ~1-2% take rate

There is no Apr 15 "coverage break." The midpoint just happened to fall right after the parse-failure spike subsided.

## Strict-rigor receipts

- Per-day breakdown queried directly from `C:/arcis/data/archive/ai_research_desk_bootcamp_2026-04-24.sqlite3` (`mode=ro`)
- Conviction distribution per day cross-referenced against parser code at `src/llm/packet_writer.py:692,701,710`
- Model version source: JOIN against `recommendations.model_version`
- No code changes — this is a doc-only deliverable closing an investigation tracker

## Sibling trackers
- #846 — canonical `llm_action` labels (PR #849)
- #847 — conviction-band scale fix (PR #851)
- **#848 (this doc)** — coverage-drop investigation
- #850 — conviction=5 parse-failure pollution (filed by #847)
