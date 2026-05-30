# Spec — Wire 3 dead-weight Finnhub collectors (W21, v0.36.38)

## Goal

Wire the 3 paid-but-unused ("dead-weight") Finnhub capabilities into overnight
data collection. We pay for these on the Finnhub plan but no collectors exist
(confirmed: no scaffolding in `src/data_collection/`):

- **company_executive** — Finnhub `/stock/executive`
- **stock_financials** — Finnhub `/stock/metric` or `/stock/financials-reported`
  (pick the one matching what we actually pay for; verify against the plan)
- **price_target** — Finnhub `/stock/price-target`

## Per-capability deliverables

For EACH capability:

1. **Registry table** in `src/schema/registry.py` — design columns from the
   Finnhub response shape; `ticker` + `as_of`/`collected_at` + sensible PK;
   add a UNIQUE index for the upsert key.
2. **Collector module** in `src/data_collection/` — use
   `src/data_collection/_finnhub_shared.py` (`get_finnhub_key()`) for HTTP/auth;
   raise `CollectorConfigError` on missing key; raise
   `CollectorPartialFailureError` on >50% mass failure (mirror
   `analyst_collector.py` + the v0.36.26 `_run_plan_gated_collector` path).
3. **Overnight wiring** in `src/scheduler/overnight.py` — these are plan-gated
   capabilities → route through `_run_plan_gated_collector`.
4. **TDD** — Finnhub fully mocked (NO network in tests); mirror
   `tests/data_collection/` patterns.
5. **Schema sync** — registry → `validate-schema --fix` → `render_migrate` (PG).

## Templates to study first

- `src/data_collection/institutional_ownership_collector.py` (v0.36.25/26)
- `src/data_collection/analyst_collector.py` (mass-failure raise)
- `src/scheduler/overnight.py` `_run_plan_gated_collector` (plan-gating)

## Hard constraints (CLAUDE.md)

- Schema registry is the SINGLE source of truth — NO `CREATE`/`ALTER TABLE`
  outside `src/schema/registry.py`.
- Mock ALL external APIs in tests (no network from pytest).
- Test count must not drop (add tests, don't remove).
- Apply the sibling-search rule; strict rigor, no hand-waving.

## Scope fence

`src/data_collection/`, `src/schema/registry.py`, `src/scheduler/overnight.py`,
`tests/`. Do NOT touch executor/reconcile/auditor or unrelated collectors.

## Out of scope

F-24 (collector-contract `CollectorResult` refactor) — comes after, separately.

## Versioning

Deliver as **v0.36.38** (CHANGELOG entry + `src/version.py` bump). W21
collector-wiring deliverable; operator has consciously lifted the no-features
rule for using paid capacity already paid for.
