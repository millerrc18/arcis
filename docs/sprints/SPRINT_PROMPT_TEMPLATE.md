# CC Sprint Prompt Template

Copy and customize this template for each new CC sprint.

---

## Template

```
First, check out a new feature branch:

git checkout main
git pull origin main
git checkout -b feat/{BRANCH_NAME}

You are now on branch feat/{BRANCH_NAME}. Read docs/sprints/{SPRINT_FILE} and execute all tasks.

Rules:
- Do NOT merge to main. Push to the feature branch only.
- Close the following GitHub issues upon completion: {ISSUE_NUMBERS}
- Follow the 3× Ralph Loop protocol for each major deliverable:
  Pass 1: Implement the feature/fix
  Pass 2: Review for gaps, errors, missed edge cases, untested paths
  Pass 3: Fix everything from Pass 2, polish, verify
- Run the full test suite before and after. Pass count must not decrease.
- Frontend must build: cd frontend && npm run build
- Update MASTER.md Section 2 (volatile counts) if any counts changed.
- Add entries to RELEASES.md and CHANGELOG.md.
- Every commit must be atomic (one logical change per commit).
- Push to feature branch when complete:
  git push origin feat/{BRANCH_NAME}
```

---

## Examples

### Gap Assessment Sprint
```
First, check out a new feature branch:

git checkout main
git pull origin main
git checkout -b feat/gap-assessment-top3

You are now on branch feat/gap-assessment-top3. Read docs/sprints/sprint-gap-assessment-top3.md and execute all 3 tasks.

Rules:
- Do NOT merge to main. Push to the feature branch only.
- Close #295, #296, #297 upon completion.
- Follow the 3× Ralph Loop protocol for each task.
- Run the full test suite before and after. Pass count must not decrease.
- Frontend must build: cd frontend && npm run build
- Update MASTER.md and RELEASES.md.
- Push to feature branch when complete.
```

### Simulation Engine Sprint
```
First, check out a new feature branch:

git checkout main
git pull origin main
git checkout -b feat/simulation-engine

You are now on branch feat/simulation-engine. Read docs/sprints/sprint-simulation-engine.md and execute all 14 tasks.

Rules:
- Do NOT merge to main. Push to the feature branch only.
- Follow the 3× Ralph Loop protocol for each major deliverable.
- Run the full test suite before and after. Pass count must not decrease.
- Frontend must build: cd frontend && npm run build
- Update MASTER.md and RELEASES.md.
- Push to feature branch when complete.
```

### Bloomberg UI Sprint
```
First, check out a new feature branch:

git checkout main
git pull origin main
git checkout -b feat/ui-bloomberg

You are now on branch feat/ui-bloomberg. Read docs/sprints/sprint-ui-bloomberg.md and execute all 4 phases.

Rules:
- Do NOT merge to main. Push to the feature branch only.
- This is a frontend-only sprint — do not modify any files outside frontend/src/.
- Follow the 3× Ralph Loop protocol for each of the 18 dashboard pages.
- Every page must pass the independent agent auditor at 9.0/10 or higher.
- Frontend must build: cd frontend && npm run build
- Push to feature branch when complete.
```
