# Sprint 4 visual-verify — `after/` results

**Captured**: 2026-05-08 (T23 sprint closeout)
**Deployment**: `https://halcyonlab.app` serving `ad38da2` (v0.34.0)
**Verified via**: header shows `ARCIS v0.34.0` on all pages

## 11 priority pages

| Slot | Filename | Page | Result | Notes |
|------|----------|------|--------|-------|
| 01 | `01-dashboard.png` | / (Dashboard) | PASS | KPIStrip renders all 5 cards; TOTAL P&L `$454.02` GREEN with `n=14 · canonical` badge; TL: HOLD; BUILD SCORE 17.7 |
| 03 | `03-shadow-ledger.png` | /shadow-ledger | PASS | Shadow Ledger loads; closed-tab P&L values show correct sign formatting (Sprint 4 T18b fix) |
| 05 | `05-trade-history.png` | /trade-history | PASS | Trade History renders; Excess Sharpe panel with cohort badge present (Sprint 3 T12) |
| 06 | `06-strategy.png` | /strategy | PASS | Strategy page loads with cohort badge from /api/strategy-detail._meta |
| 09 | `09-cto-report.png` | /cto-report | PASS | CTO Report generates; _meta envelope present |
| 10 | `10-attribution.png` | /attribution | PASS | Attribution renders; paired-overlap gate visible |
| 11 | `11-model-perf.png` | /model-performance | PASS | Model Performance renders |
| 15 | `15-stress-test.png` | /stress-test | PASS | Stress Test renders |
| 21 | `21-monitoring.png` | /monitoring | PASS | Monitoring renders gracefully (system_metrics is local-only note as expected) |
| 23 | `23-settings.png` | /settings | PASS | Settings page renders; risk inputs display clamped values (no float32 noise) |
| 24 | `24-roadmap.png` | /roadmap | PASS | Roadmap renders |

## 2 new components (no before/ baseline)

| Slot | Filename | Component | Result | Acceptance criteria |
|------|----------|-----------|--------|---------------------|
| 25 | `25-kpi-pnl-card.png` | TOTAL P&L KPI card (T12) | PASS | `$454.02` dollar format ✓, meta badge `n=14 · canonical` visible ✓, value GREEN (non-zero) ✓, no console errors observed ✓ |
| 26 | `26-notifications-health-panel.png` | NotificationsHealthPanel (T15) | PASS | `success_rate=85%` numeric ✓, `fail_count=63` numeric ✓, `dedup_hits=12` numeric ✓, `oldest_unack_alert=2026-05-08 08:59` non-null (expected — real alerts exist) ✓, no `--` placeholders ✓ |

## Summary

**13 of 13 checks: PASS**

All Sprint 4 UI changes are rendering correctly on the live Render deployment (`ad38da2` / v0.34.0).

Notable findings:
- TL header shows `HOLD` (not the pre-Sprint-3 `TL: NOT SET` or `TL: ...`) — Sprint 3 T12 fix confirmed live
- NotificationsHealthPanel `oldest_unack_alert` is non-null (`2026-05-08 08:59`) — this is expected; there are real unacknowledged alerts in production, not a UI bug
- NotificationsHealthPanel `success_rate=85%` is amber (≥80% threshold) — 63 failures in 24h; operator should investigate `notifications_sent` table. Not a UI bug.
- P&L card shows `$454.02` GREEN which matches API total_pnl_dollars for canonical instrumented cohort
