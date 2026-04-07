# Arcis Merge & Release Plan — April 6, 2026

## Current State

**13 open PRs. 15 open issues. 4 feature branches. 34 stale branches.**

---

## PR Classification

### 🔴 HOTFIX — Merge to main immediately

| PR | Title | Risk | Issues Closed |
|---|---|---|---|
| **#313** | Log rectification — 6 production bugs | **CRITICAL** — exit cascade depleting buying power, 337 errors/day | #310, #311, #308, #309, #307, #302 |

**PR #313 is your top priority.** It fixes the shadow trade exit cascade that's stuck 12 symbols and depleted buying power to $0. This is actively harming the paper account. Merge this BEFORE any feature work.

**Merge command:**
```powershell
git checkout main && git pull origin main
git merge origin/fix/log-review-rectification-2026-04-06 --no-ff
# Review the 17 changed files — check for stubs/TODOs per rule #28
git push origin main
git tag -a v0.14.1 -m "v0.14.1 — hotfix: exit cascade, type safety, conviction parsing, schema drift"
git push origin v0.14.1
```

---

### 🟡 CODEX FIXES — Review, then merge the newer one

| PR | Title | Status |
|---|---|---|
| #298 | Telegram markdown fix v1 | **SUPERSEDED by #305** — close without merging |
| #305 | Telegram markdown fix v2 + type safety + fundamentals | Review, then merge |

PR #305 is the second iteration that subsumes #298. Close #298, review #305, merge if clean. This addresses issues #299, #300, #301.

**Action:**
```powershell
# Close #298 without merging (superseded)
# Review #305 carefully (check for stubs per rule #28)
# If clean:
git merge origin/codex/investigate-telegram-markdown-error-5c095o --no-ff
git push origin main
```

---

### 🟢 DEPENDABOT — Batch merge safe ones, close superseded

| PR | Package | Action |
|---|---|---|
| #213 | actions/checkout 4→6 | ✅ Merge (CI action, low risk) |
| #214 | actions/setup-node 4→6 | ✅ Merge (CI action, low risk) |
| #215 | actions/setup-python 5→6 | ✅ Merge (CI action, low risk) |
| #216 | react-router-dom 7.13→7.14 | ✅ Merge (minor bump) |
| #217 | yfinance <1.0→<2.0 | ⚠️ Review — major version range change. Test yfinance 2.x compatibility |
| #218 | vite 8.0.2→8.0.3 | ❌ Close — superseded by #306 |
| #219 | lucide-react 1.0.1→1.7.0 | ⚠️ Review — major jump. Check for breaking icon name changes |
| #220 | react-query 5.95→5.96 | ✅ Merge (patch bump) |
| #221 | eslint 9.39→10.2 | ⚠️ Review — major version. May have new lint rules that break build |
| #306 | vite 8.0.2→8.0.5 | ✅ Merge (supersedes #218) |

**Batch merge the safe ones:**
```powershell
# Merge safe Dependabot PRs
for pr in 213 214 215 216 220 306; do
    # GitHub UI: click "Merge" on each, or via API
done
# Close superseded: #218
# Review before merge: #217 (yfinance), #219 (lucide-react), #221 (eslint)
```

---

### 🔵 FEATURE BRANCHES — Do NOT merge yet, test first

| Branch | Commits Ahead | Status | Notes |
|---|---|---|---|
| `feat/gap-assessment-top3` | 3 | ✅ Complete | Leakage detection, council weights, ranker RS. Closes #295-297 |
| `feat/simulation-engine` | 1 | ✅ Complete | 13-scenario engine, Monte Carlo, TL validation |
| `feat/model-performance` | 4 | ⚠️ Cross-contaminated | Has simulation commit + Bloomberg UI commit merged in. Needs rebase |
| `feat/ui-bloomberg` | Not on remote | 🔄 In progress? | Check with CC |

**Problem with `feat/model-performance`:** It has commits from the simulation engine AND a Bloomberg UI commit mixed in. This happened because CC merged main (which had been updated) into its branch. Before merging, this needs a clean rebase or we accept the merge commits.

---

## Recommended Merge Order

```
Phase 1: HOTFIXES (do today)
  1. Merge PR #313 (exit cascade fix) → tag v0.14.1
  2. Review + merge PR #305 (telegram/type safety)
  3. Close PR #298 (superseded by #305)

Phase 2: DEPENDABOT (do today, low risk)
  4. Merge #213, #214, #215 (CI actions)
  5. Merge #216, #220, #306 (safe npm bumps)
  6. Close #218 (superseded by #306)
  7. Review #217 (yfinance), #219 (lucide-react), #221 (eslint) — merge if safe

Phase 3: FEATURE BRANCHES (after testing)
  8. Test feat/gap-assessment-top3 locally → merge → tag v0.15.0
  9. Test feat/simulation-engine locally → merge
  10. Test feat/model-performance locally → merge (may need rebase first)
  11. Test feat/ui-bloomberg locally → merge
  12. Tag v0.16.0 (or v0.17.0 if all 4 features)

Phase 4: CLEANUP
  13. Delete 34 stale remote branches (proto/*, archive/*, etc.)
  14. Close any issues resolved by merged PRs
  15. Update MASTER.md with new counts
```

---

## Stale Branch Cleanup

34 remote branches should be deleted:

```powershell
# Delete all stale branches (proto/*, archive/*, claude/*, etc.)
# Preview first:
git branch -r | grep -E "proto/|archive/|claude/|audit-run|mega-sprint|codex/" | sed 's/origin\///'

# Then delete:
git branch -r | grep -E "proto/|archive/|claude/|audit-run|mega-sprint" | sed 's/origin\///' | xargs -I{} git push origin --delete {}
```

Keep: `main`, `feat/*` (active), `fix/*` (active), `dependabot/*` (managed by bot), `research/*` (if active).

---

## Testing Protocol for Feature Branches

Before merging each feature branch:

```powershell
git checkout feat/gap-assessment-top3   # (or whichever branch)

# Backend
python -m pytest tests/ -x -q

# Frontend
cd frontend && npm run build && cd ..

# Smoke test
python -m src.main serve &
cd frontend && npm run dev
# Click through affected pages in browser
# Kill both processes

# If all pass → merge to main
```

---

## Versioning After All Merges

| Tag | Includes |
|---|---|
| v0.14.1 | Hotfix: exit cascade, type safety, conviction, schema drift (PR #313) |
| v0.15.0 | Gap assessment: leakage detection, council weights, ranker RS |
| v0.16.0 | Simulation engine + model performance + Bloomberg UI |

Or consolidate the 4 feature branches into one release:
| v0.15.0 | All 4 feature branches (gap assessment + sim + model perf + UI) |

I'd recommend the consolidated approach — one big release with proper RC testing, rather than 3 intermediate tags that each deploy to Render.
