# Versioning policy

_Owners: PM + operator. Authoritative as of v0.32.0._

This repo follows **semantic versioning** (semver) with sprint-aware release cadence. Forward-going rule: **every merged PR updates `CHANGELOG.md`**, and **every release cut updates `src/version.py` + creates a git tag**.

## Version components

```
vMAJOR.MINOR.PATCH
```

- **MAJOR** — breaking changes (rare; this codebase has stayed pre-1.0 since inception).
- **MINOR** — new features, methodology shifts, sprint completions, schema additions, anything that changes what the system does or what an operator sees.
- **PATCH** — bug fixes, hotfixes, doc clarifications, test additions, internal refactors that don't change behavior.

Pre-release suffixes (`-alpha1`, `-rc1`) are allowed when cutting a tag mid-sprint, but should be rare. Prefer waiting for the sprint to close.

## What requires a version bump

| Change type | Bump |
|---|---|
| New feature module (e.g. wires methodology shelf into runtime) | MINOR |
| Schema add (`ColumnDef` / `TableDef` to `src/schema/registry.py`) | MINOR |
| Pre-registration document changes | MINOR |
| Bug fix (silent failure, race, off-by-one) | PATCH |
| Hotfix to recent release | PATCH |
| Doc-only change (CHANGELOG, README, docs/) | PATCH |
| Test-only change | PATCH |
| Refactor with no behavior change | PATCH |
| Operator-facing UI change | MINOR if scope > cosmetic, else PATCH |
| Methodology change post-pre-reg-cut | **STOP** — pre-reg §5.3 forbids; needs operator + addendum |

## Where to update

Every release cut touches **three** places in lockstep. Inconsistency between these is the bug `src/version.py` was created to prevent.

1. **`CHANGELOG.md`** — move `[Unreleased]` items into a new dated section at the top. Use `[vX.Y.Z] - YYYY-MM-DD — short release theme`. Sections: Release summary / Added / Changed / Fixed / Decisions / Deferred (omit empty).
2. **`src/version.py`** — bump `VERSION` constant + comment to match.
3. **Git tag** — `git tag -a vX.Y.Z -m "Short release theme"` on the merge commit that completes the release; `git push origin vX.Y.Z` separately.

The frontend reads `status.version` from `/api/system/status` which reads `src/version.py`. Drift between version.py and CHANGELOG header has happened before (pre-#631 the value was hardcoded in three frontends — that incident is what created `src/version.py`).

## Per-PR cadence (the forward-going rule)

**Every merged PR adds an entry to `CHANGELOG.md` under `[Unreleased]`** before merge. The PR body should reference the line being added.

When a release is cut (typically at end of sprint or natural feature boundary):

1. PM moves `[Unreleased]` items into a new `[vX.Y.Z]` section with a release summary.
2. PM bumps `src/version.py`.
3. PM cuts the git tag: `git tag -a vX.Y.Z -m "<theme>" <merge-commit-sha>` then pushes.
4. PM annotates which PR was the "tag-cut" boundary in the release summary.

A release can bundle 1 PR or 50 PRs. Granularity is the PM's call based on theme coherence and operator-visible scope. Past pattern: minor releases tend to bundle a sprint's worth of work; patches are immediate hotfixes between sprints.

## Pre-release tags

Avoid unless cutting a public test build. Pattern: `vX.Y.Z-alpha1`, `vX.Y.Z-rc1`. The `v0.24.0-alpha1` pattern from earlier history was a stage-of-implementation marker that drifted from CHANGELOG headers — discouraged going forward.

## Retroactive versioning (rare)

This was done once at v0.32.0 to close a gap where v0.27.1 → v0.32.0 went un-tagged for ~3 days while ~60 PRs landed. The post-mortem decision: bundle by theme into 5 retroactive minor releases (v0.28.0, v0.29.0, v0.30.0, v0.31.0, v0.32.0) and document each in `CHANGELOG.md`.

Tag-cut SHAs for those retroactive releases (cut on the commit that completed each theme):

| Tag | Completes | Commit SHA |
|---|---|---|
| `v0.28.0` | Sprint 0 wave-system + 0.B-0.D consolidation | (cut at most-recent #793-era commit on main) |
| `v0.29.0` | Sprint 1.A.x PIT discipline (closes #802, #813, #818, #821) | (cut at #821 merge) |
| `v0.30.0` | Reconcile + dashboard sprint Tier 1.A-1.F | (cut at #833 merge) |
| `v0.31.0` | Sprint 1.B walk-forward + methodology wiring | (cut at #845 merge) |
| `v0.32.0` | Sprint 1.C Phase 1+2 attribution + PIT audit | (cut at #853 merge — current main) |

The PM identifies the SHA at PR-merge time and operator pushes the tag (operator-side authority on tag pushes; PM never pushes tags unilaterally).

Retroactive versioning should be rare. If the gap grows beyond ~10 PRs, the PM should pause to cut a release before continuing dispatch.

## Why this exists

Three failure modes this policy prevents:

1. **Display drift**: dashboard claiming v0.17.2 while runtime is v0.24.0-alpha1 (the original incident, #631).
2. **Lost release boundary**: 60 PRs merged with no tag, no CHANGELOG, no operator-visible release note. Versioning gap from v0.27.1 → v0.32.0 (2026-04-26 → 2026-04-29) was the precipitating incident.
3. **Methodology drift after pre-reg cut**: post-pre-reg §5.3 forbids changes to commitments. Pre-reg amendments require an explicit MINOR bump + dated release entry so the binding state is auditable.
