# live-monitor Agent — Golden Test Cases

**Purpose:** Machine-readable golden cases for the live-monitor wedge-diagnostic protocol.
A future agent-test harness can grep for `EXPECTED_VERDICT:` markers to extract expected outcomes.

**Protocol reference:** `.claude/plugins/arcis/agents/live-monitor.md` (4-point wedge-diagnostic protocol).
**Background:** 2026-05-26 11:14 ET incident — the agent declared wedge on a 14-minute-stale heartbeat
that had active in-progress task markers in arcis.log. The revised protocol requires ALL FOUR conditions
to hold before wedge can be declared.

---

## CASE_A — Regression Case (2026-05-26 11:14 ET False Positive)

**CASE_ID:** A
**SCENARIO:** Heartbeat stale 14 minutes; active in-progress task markers present in arcis.log.

### Inputs

```
snapshot_timestamp: 2026-05-26 11:14 EDT
service: ArcisWatchLoop
nssm_state: RUNNING
heartbeat_age_min: 14
arcis_log_last_line_age_min: 3
last_20_log_lines_include_active_markers: true
active_marker_evidence: "[CYCLE 1048] scanning recommendations — 11:11:04 EDT"
historical_baseline_min: 12
```

### Wedge-Diagnostic Evaluation

| Condition | Required | Observed | Met? |
|-----------|----------|----------|------|
| 1. Heartbeat staleness > 20 min | > 20 min | 14 min | NO |
| 2. arcis.log silence > 20 min | > 20 min | 3 min | NO |
| 3. No in-progress task markers in last 20 log lines | absent | present (`[CYCLE 1048] scanning`) | NO |
| 4. Staleness exceeds baseline_p99 for hour-of-day | > 12 min (p99) | 14 min | YES |

**Conditions met: 1 of 4. ALL FOUR required.**

EXPECTED_VERDICT: NOT_WEDGED

### Expected Agent Behavior

The agent MUST NOT declare wedge. Conditions 1, 2, and 3 are all unmet. The heartbeat is
within normal variance (14 min < 20 min threshold), arcis.log is actively receiving lines,
and the last 20 log lines contain in-progress task markers indicating normal cycle activity.
The agent should report this as an `informational` finding with evidence of active cycle
activity, NOT as `anomaly` or `must_fix`. The 14-minute staleness alone is insufficient
for a wedge declaration.

Correct report excerpt:
```json
{
  "composite_verdict": "healthy",
  "correlations": [
    {
      "description": "Heartbeat 14 min stale but arcis.log active (cycle marker at 11:11 ET); wedge conditions NOT met (1/4)",
      "severity": "informational"
    }
  ]
}
```

---

## CASE_B — True Wedge Case

**CASE_ID:** B
**SCENARIO:** Heartbeat stale 25 minutes; arcis.log silent; no in-progress markers; staleness exceeds baseline p99.

### Inputs

```
snapshot_timestamp: 2026-05-27 14:33 EDT
service: ArcisWatchLoop
nssm_state: RUNNING
heartbeat_age_min: 25
arcis_log_last_line_age_min: 22
last_20_log_lines_include_active_markers: false
last_20_log_lines_evidence: "[CYCLE 1102] idle — 14:08:44 EDT  [last entry; no activity since]"
historical_baseline_min: 8
```

### Wedge-Diagnostic Evaluation

| Condition | Required | Observed | Met? |
|-----------|----------|----------|------|
| 1. Heartbeat staleness > 20 min | > 20 min | 25 min | YES |
| 2. arcis.log silence > 20 min | > 20 min | 22 min | YES |
| 3. No in-progress task markers in last 20 log lines | absent | absent (last entry: `idle` at 14:08) | YES |
| 4. Staleness exceeds baseline_p99 for hour-of-day | > 8 min (p99) | 25 min | YES |

**Conditions met: 4 of 4. ALL FOUR required — threshold reached.**

EXPECTED_VERDICT: WEDGED

### Expected Agent Behavior

The agent MUST declare wedge. All four conditions are met: heartbeat is 25 min stale
(> 20 min threshold), arcis.log has been silent for 22 min (> 20 min threshold), the
last 20 log lines contain no active-work indicators, and current staleness (25 min)
greatly exceeds the historical p99 baseline (8 min) for the 14:00–15:00 ET hour window.
The agent should report this as `anomaly` severity and recommend restart evaluation
via `/arcis:operate runbook watchloop-wedged`.

Correct report excerpt:
```json
{
  "composite_verdict": "unhealthy",
  "correlations": [
    {
      "description": "ArcisWatchLoop WEDGED — all 4 wedge-diagnostic conditions met: heartbeat 25 min stale, arcis.log silent 22 min, no in-progress markers, staleness exceeds p99 baseline (8 min)",
      "severity": "anomaly"
    }
  ],
  "recommendations": [
    "Run /arcis:operate runbook watchloop-wedged to evaluate restart"
  ]
}
```

---

## Harness Notes

To extract expected verdicts for automated testing:

```bash
grep "EXPECTED_VERDICT:" docs/agent-tests/live-monitor-golden.md
```

Expected output:
```
EXPECTED_VERDICT: NOT_WEDGED
EXPECTED_VERDICT: WEDGED
```

The `EXPECTED_VERDICT` marker appears exactly once per case, on its own line, in the format
`EXPECTED_VERDICT: <value>` where `<value>` is one of: `NOT_WEDGED`, `WEDGED`.
