# Stage 1 Corpus Manifest — stage1-001

**Pinned:** 2026-05-11
**Purpose:** Immutable provenance reference for future training runs. The artifact below is the authoritative Stage 1 corpus per Sprint S1-CC A1.

## Artifact

- **File:** `data/corpus/stage1-001/entries.jsonl`
- **SHA256:** `43c2e3edb2cd4bb450a890da388ec2ade49ce3205d67a0525f2bb74485606d93`
- **Size:** `202924097` bytes (`193.52` MB)
- **Row count:** 67,528 entries (verified via `wc -l`, matches `manifest.json:total_decision_points`)

## Provenance

- **Generated at:** `2026-05-11T06:18:12+00:00` (UTC, from `manifest.json:generated_at`)
- **Code SHA:** `56fd7fb7e5f34279810e49eaed2c16d46f202882`
- **Model version (writer):** `arcis:v1.0.0` (from `manifest.json:model_version`)
- **Walkforward window:** 2023-09-01 → 2026-04-28
- **§B2 admissibility:** PASS (per `manifest.json:admissibility`)
- **Parse failure count:** 124 (rate `0.001836` per `manifest.json`)

## Composition

### Row timestamps

The corpus uses `as_of` as the decision-point timestamp (one entry per ticker per trading day). Per-entry `generated_at` records the LLM writer's wallclock.

- **First entry `as_of`:** `2023-09-01` (ticker: `AAPL`, writer `generated_at`: `2026-05-01T00:20:54+00:00`)
- **Last entry `as_of`:** `2026-04-28` (ticker: `XOM`, writer `generated_at`: `2026-05-11T06:18:11+00:00`)

### model_version distribution (writer-tagged)

| model_version | count | pct |
|---|---|---|
| `arcis:v1.0.0` | 67,528 | 100.00% |

Malformed lines: 0. Missing `model_version` field: 0.

### Section PIT status (from `manifest.json:section_pit_status`)

| section | status |
|---|---|
| 1 | clean |
| 2 | clean |
| 3 | accepted-stale |
| 4 | fixed |
| 5 | fixed |
| 6 | fixed |
| 7 | fixed |
| 8 | fixed |
| 9 | best-effort |
| 10 | fixed |
| 11 | placeholder |

### Coverage limit hits (from `manifest.json:coverage_limit_hits`)

| limit | count |
|---|---|
| `fundamentals_no_cik` | 669 |
| `fundamentals_no_data` | 261 |
| `insiders_fetch_failed` | 39 |
| `macro_series_unavailable` | 504 |
| `news_coverage_gap` | 2 |
| `news_fetch_failed` | 54 |

## Cross-references

- Existing machine-readable manifest: `data/corpus/stage1-001/manifest.json`
- SHA256 file: `data/corpus/stage1-001/MANIFEST.sha256`
- Sprint spec: `docs/audits/2026-05-11-stage1-completion/sprint-spec.md`
- Generation log: `C:/arcis/halcyon-lab/logs/stage1-corpus.log` (operator-side, not in repo)
