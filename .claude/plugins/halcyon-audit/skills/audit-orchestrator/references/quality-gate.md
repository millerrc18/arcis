# Quality Gate Definition

## Gate Levels

| Gate | Criteria | Action |
|---|---|---|
| **PASS (GREEN)** | Zero critical AND zero new high AND overall health >= 7.0 | No immediate action required |
| **WARN (YELLOW)** | Zero critical AND (<=2 new high OR health 5.0-6.9) | Review findings, plan remediation |
| **FAIL (RED)** | Any critical finding OR >2 new high OR health < 5.0 | Immediate remediation required |

## Health Score Computation

Each dimension scored 1-10 based on:

| Finding Severity | Score Deduction |
|---|---|
| Critical | -3.0 per finding |
| High | -1.5 per finding |
| Medium | -0.5 per finding |
| Low | -0.1 per finding |

Base score: 10.0. Floor: 1.0. No finding in a domain = 10/10.

Overall health = arithmetic mean of all 8 dimension scores.

## Trend Arrows

Compare to most recent entry in `audit/audit_history.json`:
- Score increased by >= 0.5: up arrow
- Score decreased by >= 0.5: down arrow
- Otherwise: sideways arrow

## Label Setup Commands

Run these once on first audit (idempotent):

```bash
gh label create audit --color 0E8A16 --force
gh label create critical --color B60205 --force
gh label create high --color D93F0B --force
gh label create medium --color FBCA04 --force
gh label create low --color 0075CA --force
gh label create trading-safety --color 5319E7 --force
gh label create code-quality --color 5319E7 --force
gh label create schema-integrity --color 5319E7 --force
gh label create test-coverage --color 5319E7 --force
gh label create compliance --color 5319E7 --force
gh label create documentation --color 5319E7 --force
gh label create security --color 5319E7 --force
gh label create architecture --color 5319E7 --force
gh label create root-cause --color C2E0C6 --force
gh label create systemic --color C2E0C6 --force
```
