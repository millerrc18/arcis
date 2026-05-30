# Documentation Consolidation Audit — 2026-W21

**Branch:** `docs/2026-W21-doc-consolidation`
**Date:** 2026-05-20
**Scope:** All `*.md` / `*.rst` / `*.txt` documentation, excluding the guardrailed set
(`.claude/**` plugin & skill defs, `CLAUDE.md`, `AGENTS.md`, `LICENSE`, `CHANGELOG.md`,
`docs/versioning-policy.md`, `requirements*.txt`, and any doc modified within ~10 days
such as `docs/audits/2026-W21-*`).

## Headline

- Total doc files tracked: 630. Of those, 108 are `.claude/**` defs (off-limits).
  Repo-authored docs reviewed: 522.
- Consolidated: 1 (byte-identical duplicate). Updated: 2. Deleted: 1 (`git rm`).
  Flagged for operator: 7 items below.

### Posture

The repo deliberately retains a large, cross-linked corpus of historical sprint plans,
audit memos, ADRs, and deep-research docs. `docs/research/**` is also a CODE DEPENDENCY:
`src/api/routes/docs.py` hardcodes ~35 research docs into a served whitelist (`DOCS`), and
`scripts/verify_docs.py` counts `docs/research/*.md` against `MASTER.md`. Per the conservative
mandate I executed only clear-cut, verifiable safe changes and flagged everything ambiguous.

---

## (a) Inventory & assessment (by group)

| Group | Count | Assessment |
|---|---:|---|
| Top-level core (README, MASTER, DIRECTORY, RELEASES, CHANGELOG) | 5 | Mixed — see below |
| docs/ root guides (operator-guide, roadmap, deployment, cli-reference, capability_registry, dashboard-data-map, training-guide, telegram-commands, methodology-toolkit, instrumentation_versions) | 10 | Mostly CURRENT; `deployment.md` STALE (fixed) |
| docs/research | 100→99 | CURRENT corpus — code-served + counted; conservative-keep |
| docs/sprints | ~130 | Historical record — KEEP (heavily cross-linked) |
| docs/audits | ~90 | Historical record — KEEP (recent ones guardrailed) |
| docs/superpowers | ~22 | Historical record — KEEP |
| docs/archive | ~60 | Already archived — KEEP |
| docs/decisions (ADRs 001–012 + 2 specs) | 14 | CURRENT — KEEP |
| docs/operations | 4 | CURRENT (3 code-served) — KEEP |
| validation/diagnostics/audit(singular)/issues/journal/milestones/packet_templates/plans/platform/quality/specs/blueprint/design/diagrams | ~40 | Mostly historical — KEEP; flags below |
| `.claude/**` | 108 | OFF-LIMITS |

### Reality cross-checks

- Current version `v0.36.41` (CHANGELOG) / `src/version.py` anchors `v0.36.0`. README badge said
  `v0.27.0`; MASTER.md §1 says `v0.27.0` (both stale).
- SQLite→Postgres cutover + Render decommission are real (`docs/operations/render-decommission.md`,
  `docs/audits/2026-05-10-cloudflare-tunnel-cutover/`). Docs calling Render "live" or SQLite "the
  runtime DB" are stale.
- Actual counts: `src/*.py`=380, dashboard pages=45, research docs=100. README said 91 research;
  DIRECTORY.md (auto-gen, 2026-04-04) said 202 py / 18 pages / 79 research / 49 tables.
- `src/api/routes/docs.py` DOCS whitelist verified — those research/ops docs must NOT be deleted.

---

## (b) Consolidated (before → after)

| Before | After | Rationale |
|---|---|---|
| `docs/research/Algorithmic_Trader_Tax_Strategy__TTS_and_475f_Election.md` | merged into `docs/research/Algorithmic_Trader_Tax_Strategy_TTS_475f.md` | Byte-identical (`diff` exit 0, both 220L). Kept the variant cited by `docs/sprints/roadmap-spec-coverage-audit.md`; deleted the variant referenced only by auto-generated `DIRECTORY.md`. |

---

## (c) Updated

| File | Change |
|---|---|
| `README.md` | Version badge `v0.27.0`→`v0.36.x`; removed `logo=render` from dashboard badge; rewrote Dashboard/Cloud/Tech-Stack/Ops lines to Cloudflare Tunnel + local PostgreSQL (Render + SQLite-runtime removed); research count 91→100; replaced stale `scripts/render_migrate.py` step with neutral wording. "Current Status" narrative left intact and flagged (#2). |
| `docs/deployment.md` | Title → "(DEPRECATED)" + banner: Render decommissioned, runtime DB is local Postgres, pointers to `render-decommission.md`, the cutover spec, and `operator-guide.md`. Historical body retained for rollback context. |

---

## (d) Deleted (`git rm`, history preserved)

| File | Rationale |
|---|---|
| `docs/research/Algorithmic_Trader_Tax_Strategy__TTS_and_475f_Election.md` | Exact byte-for-byte duplicate of `..._TTS_475f.md`. Only inbound link was auto-generated `DIRECTORY.md`; surviving copy is the one cited by `roadmap-spec-coverage-audit.md`. No code reference. |

Note: drops research/*.md 100→99. MASTER.md documents 92 so `verify_docs.py` already WARNs (+8/+7)
regardless — no NEW failure introduced. MASTER.md is guardrailed and was not edited.

---

## (e) NEEDS OPERATOR DECISION

1. **MASTER.md §1 is stale** (`v0.27.0`, "Render static + Python API", "SQLite raw sqlite3"). It is
   the declared single source of truth and is guardrailed (modified 2026-05-16, inside the 10-day
   window). Recommend: refresh §1 identity/release/tech-stack to v0.36.x + Cloudflare Tunnel +
   Postgres. Left untouched to avoid colliding with active work.

2. **README.md "Current Status" + "2026-04-27 Audit Artifacts"** still describe the v0.27.0 / Track-1.5
   / Stage-1 phase as present state. I fixed verifiable facts but left the phase narrative (rewriting it
   correctly needs the current trading-phase posture I couldn't verify from docs). Recommend: refresh,
   or point at `docs/roadmap.md` (current to Sprint 6 / v0.36.0).

3. **DIRECTORY.md is auto-generated and stale** (202 py / 18 pages / 79 research / 49 tables vs actual
   380 / 45 / ~99 / 67+). Fix is to re-run `scripts/generate_directory.py`, not hand-edit. Caveat: the
   script's `ANNOTATIONS` dict (code, out of scope) still describes Render/SQLite, so a clean regen
   also needs a small code edit. Recommend: operator re-runs the generator after updating annotations.

4. **`docs/audit/` (singular, 5 files) vs `docs/audits/` (plural)** — two parallel audit trees. Singular
   holds 5 db-sync / live-state forensic docs (2026-04-20 → 2026-05-03). Recommend: move them into
   `docs/audits/` (e.g. `2026-05-03-db-sync/`). Left as-is to avoid chasing inbound links.

5. **`docs/deployment.md` — keep deprecated stub vs delete.** Added a banner rather than `git rm`; a
   deployment-guide deletion is operator-risky and the Render rollback path has historical value.
   Recommend: keep the deprecated stub one more cycle, delete after render-decommission Phase 4.

6. **Apparent research "v1/v2" pairs are NOT duplicates** (verified distinct content + sizes):
   `Complete_Research_Agenda__Validation_to_Scale{,_v2}`, `AI_Council_Redesign__5-Agent_Strategic_Brain`
   vs `..._v2__Architecture_and_Implementation`, `The_Halcyon_Framework{,_v2}`,
   `15_Algorithm_Gap_Assessment` vs `2026-04-05-15-algorithms-gap-analysis`. Several are code-served
   and/or cross-linked. Recommend: keep all (flagged so operator knows they were reviewed).

7. **`docs/quality/` vs `docs/archive/quality/`** each have `improvement_log.md` + `issue_log.md`. NOT
   duplicates — active copies are larger/newer; archive copies are older snapshots. Recommend: keep both.

---

## Method notes / honesty

- Conservative by design: the corpus is large and intentionally cross-referenced; the mandate prioritizes
  avoiding a costly wrong deletion. Only one deletion was clear-cut enough (byte-identical) to execute.
- Did NOT run `generate_directory.py` or `verify_docs.py` (would execute project code; the generator also
  depends on a stale code-side annotations dict). DIRECTORY.md staleness is flagged instead.
- Could not independently verify the current trading phase from docs alone — hence the README/MASTER
  status narratives were flagged, not rewritten.
- All `.claude/**`, config, code, and recent (≤10-day) audit/design docs were left untouched.
