# Error Envelopes — `arcis:strategy`

Read-only reference. Uniform shape: `<REFUSE | ERROR> — <verb>: <summary>`. 16 envelopes (after DA-revision: 10.12-10.16 added).

## 10.1 Verb-unknown

```
ERROR — unknown verb: "<received>". Expected one of: ideate, backtest, analyze, status.
Usage: ...
```

## 10.2 PROD-PG refused

```
REFUSE — backtest: ARCIS_ALLOW_PROD_PG is set.
  Reason: arcis:strategy writes ONLY to local research DB. Prod-PG writes are forbidden by skill policy.
  Resolution: unset ARCIS_ALLOW_PROD_PG and re-run.

No mutation attempted. No audit event for mutation written.
```

## 10.3 Spec not found

```
ERROR — backtest: spec resolution failed for "<strategy_id>":
  Type: FileNotFoundError
  Detail: src/platform/specs/<strategy_id>.yaml does not exist
  Resolution: confirm spec file exists and re-run. Available specs: <list from list_available_specs()>
```

## 10.4 Spec malformed

```
ERROR — backtest: spec resolution failed for "<strategy_id>":
  Type: ValueError
  Detail: <validate_spec error message>
  Resolution: fix the YAML at src/platform/specs/<strategy_id>.yaml and re-run.
```

## 10.5 R8 firewall violation

```
REFUSE — R8 firewall preflight failed for <strategy_id>:
  <verbatim R8ViolationError message>
  
  R8 requires the strategy YAML to declare a `derived_from` key (value may be null OR a dict
  with source_type ∈ {forensic_audit_ruleset, bootcamp_backtest, shadow_trading_cohort, other},
  source_run_id (regex [A-Za-z0-9_.\-]+), source_date_range {start, end}, optional source_trade_ids).
  
  Resolution: add `derived_from:` to src/platform/specs/<strategy_id>.yaml and re-run.
  
  No mutation attempted. No backtest tables written.
```

## 10.6 Engine failure (mid-run)

```
ERROR — backtest: engine raised unexpectedly:
  <verbatim Python exception class + message + first 3 lines of stack>
  
  Phase: <B6 (--quick) | B7 window <N> IS-slice | B7 window <N> OOS-slice>
  Strategy: <strategy_id>
  spec_hash: <hash>
  
  No further mutations attempted. Partial state may exist:
    is_persist_result_ids written so far: [<list>]
  
  Resolution: inspect partial rows via /arcis:strategy status <strategy_id>; manually clean up if needed.
```

## 10.7 Walkforward runner failure

```
ERROR — backtest: walkforward runner raised unexpectedly:
  <verbatim Python exception class + message>
  
  Strategy: <strategy_id>
  spec_hash: <hash>
  Windows processed before failure: <N>
  
  Note: per-window IS backtest_results rows DID persist (the runner failed at aggregation, not per-window engine).
  No walkforward_results row written. No trials_registry row written.
  
  Resolution: inspect IS rows via /arcis:strategy status; investigate runner error.
```

## 10.8 Corpus binding failure (defensive — v1 leaves corpus_id=None)

```
REFUSE — backtest: corpus manifest missing for declared corpus_id <id>:
  <verbatim RuntimeError message from FA7 line 233-244>
  
  Resolution: either bind a corpus via the (future) corpus verb, or leave config.corpus_id=None for v1.
  
  v1 default behavior is corpus_id=None — this error indicates the implementing PM set corpus_id explicitly.
```

## 10.9 Unknown action / unknown run-id (analyze)

```
ERROR — analyze: unknown run-id: "<received>". Not found in backtest_results or walkforward_results.
  Resolution: verify the id with /arcis:strategy status; re-run with correct id.
```

## 10.10 Operator denial at confirm

```
backtest CANCELLED by operator at Phase B4. No mutation attempted. Audit event arcis_strategy.backtest.cancelled written.
```

## 10.11 Tool unavailable (graceful degradation)

```
WARNING — tool <name> not available (python -m src.tools.<name> --help exited non-zero).
  Affected: <verb step>
  Continuing with reduced output. Refresh tooling or re-run.
```

## 10.12 Concurrent backtest refused (DA5)

```
ERROR — backtest: concurrent backtest detected for <strategy_id>.
  Another /arcis:strategy backtest run is currently holding the lock at data/locks/strategy/<strategy_id>.lock.
  Started: <lock_held_since>
  
  Refusing to overlap (concurrent writes to the same strategy_id would corrupt audit invariants).
  
  Resolution: wait for the active run to complete (see /arcis:strategy status — Active Runs section).
  Or use --force to bypass (NOT recommended).
```

## 10.13 db_path matches prod-PG signature (DA9 — defense-in-depth)

```
REFUSE — backtest: resolved db_path matches a prod-PG signature.
  db_path (last 30 chars): ...<tail>
  Matched signature: <signature>
  
  Reason: arcis:strategy writes ONLY to local research DB. Defense-in-depth check inside heredoc.
  Resolution: confirm arcis_config.yaml paths.db_canonical points to local SQLite or pg.test_dsn (port 5434).
  
  No mutation attempted. No audit event for mutation written.
```

## 10.14 Analyze refused on orphan IS row (DA1)

```
REFUSE — analyze: result_id <result_id> is from a partial walkforward run that did NOT complete.
  provenance_kind: wf_is_window_orphan_partial_run
  strategy_id: <strategy_id>
  
  The walkforward aggregation step failed mid-run; this IS slice is forensic-only.
  No walkforward_results row exists; no OOS validation was performed.
  
  Resolution: re-run /arcis:strategy backtest <strategy_id> to produce a clean walkforward result.
  If you need to inspect the orphan IS metrics for debugging, query backtest_results directly
  via /arcis:strategy status <strategy_id> (Orphans section).
```

## 10.15 Ideate incomplete — research-domain-lead missing (DA6)

```
ERROR — ideate: research-domain-lead did not return findings within Wave A budget (8 min).
  research-domain-lead is REQUIRED for synthesis.
  
  Wave A status:
    research-domain-lead: <status>
    db-investigator:      <status>
    git-historian:        <status>
  
  Resolution: re-run with extended budget:
    /arcis:strategy ideate "<theme>" --extended-wave-a-budget 16
  Or dispatch research-domain-lead directly for diagnostic:
    /arcis:research domain-lead "<theme>"
  
  No report written. No partial synthesis surfaced.
```

## 10.16 Analyze WARNING — variance fallback fired (DA13)

```
WARNING — analyze: DSR computed against variance fallback (trials_registry has <N> trials, below 20 threshold).
  Source: _VARIANCE_FALLBACK = 0.02/250 (trials.py:33; RuntimeWarning emitted at trials.py:109).
  variance_source: fallback_with_warning
  
  This is informational — analyze continues. DSR is computed with the documented fallback variance,
  which is a conservative under-estimate of true family variance. Forensic recovery 6 months later
  can use the audit-event params.variance_source field to determine if this fallback was active.
```
