# Extensive Repo Audit — 2026-03-29

## Scope

This audit covered the repository from `AGENTS.md` outward:

- Governance and product docs
- Runtime architecture and deployment docs
- Core trading, risk, council, API, scheduler, training, and notification code paths
- Test suite behavior and representative end-to-end reproductions

Primary sources reviewed:

- `AGENTS.md`
- `README.md`
- `docs/architecture.md`
- `docs/training-guide.md`
- `docs/roadmap.md`
- `docs/deployment.md`
- `docs/cli-reference.md`
- `docs/system-state-2026-03-27.md`
- `config/settings.example.yaml`

Audit methods:

- Static review of major subsystems in `src/`
- Targeted `pytest` runs across the suite
- Direct reproductions for high-risk execution paths
- Schema/contract tracing between docs, code, and tests

Important context:

- The working tree is already heavily dirty. No existing user changes were reverted.
- `gh` is not installed in this environment, so GitHub issue creation was performed via the GitHub REST API using a verified PAT.

## Executive Summary

The repo contains strong ambition, a wide feature surface, and real evidence of systems thinking. It also has a recurring failure mode: subsystem migrations are being completed in code faster than contracts, schemas, and operator safety controls are being reconciled around them.

The most serious defects are not cosmetic:

1. The active shadow-trading validator is incompatible with the actual `TradePacket` schema and rejects real packets before execution.
2. Several live-trading safety and close-out paths can desynchronize the journal from the broker.
3. The AI council redesign is only partially migrated: tests are broken, public contracts drifted, and multiple council queries target columns that do not exist in the current database schema.

This matters strategically because the project explicitly treats training data quality as its moat. Right now, the codebase still allows broker truth, journal truth, and training truth to diverge.

## Severity Summary

| Severity | Count | Themes |
| --- | --- | --- |
| Critical | 3 | Shadow execution blocked; live broker/journal truth; live safety fail-open |
| High | 4 | Council migration drift; council data blindness; local close path; phantom paper trades |
| Medium | 2 | Ambient kill-switch state; broken open-trade notifications |
| Low | 2 | Date-sensitive tests; orchestration size guardrail broken |

Confidence legend:

- High: directly reproduced or supported by failing tests and code inspection
- Medium: strongly supported by code paths, but not exercised end-to-end in this audit
- Low: likely true, but primarily maintainability/process oriented

## Issue Tracker

Opened during this audit:

- #40: `LLM validator rejects real TradePacket schema and blocks shadow execution`
- #41: `Live exit paths close the journal before broker confirmation`
- #42: `Live trading safety checks fail open on state-query errors`
- #43: `Council v2 migration broke public contracts and session compatibility`
- #44: `Council agents query the wrong database schema and lose context`
- #45: `Local /shadow/close route can close live trades without broker exit`
- #46: `Paper trades are recorded as open even when Alpaca submission fails`
- #47: `Kill-switch state is ambient and contaminates tests and environments`
- #48: `Watch loop trade-open Telegram notifications use nonexistent fields`
- #49: `Feature-engine tests are date-sensitive on non-business days`
- #50: `main.py exceeds its own size guardrail`

## Findings

### Critical

#### C1. `validate_llm_output()` is incompatible with the real `TradePacket` schema

- Confidence: High
- Impact: Blocks current bootcamp-mode shadow execution for real packets
- Evidence:
  - `src/llm/validator.py` reads `packet.entry_price` and treats `packet.stop_invalidation` as numeric.
  - `src/schemas.py` defines `TradePacket.entry_zone: str` and `TradePacket.stop_invalidation: str`; there is no `entry_price` field.
  - Direct reproduction with a real `TradePacket` raised `TypeError: '>' not supported between instances of 'str' and 'int'`.
  - End-to-end reproduction through `open_shadow_trade()` logged `[VALIDATE] Validation check failed ... REJECTING trade` and returned `None`.
  - `tests/test_llm_validator.py` passes because it uses a synthetic object shaped to the validator's assumptions, not the real schema.
- Root cause:
  - The validator is validating a legacy packet contract while the runtime uses string-formatted packet fields.
- Recommendation:
  - Centralize a single canonical numeric normalization step for packet execution fields.
  - Either:
    - parse `entry_zone`, `stop_invalidation`, and `targets` into an execution DTO before validation, or
    - extend `TradePacket` to carry canonical numeric execution fields alongside rendered strings.
  - Update validator tests to use real `TradePacket` objects, not `SimpleNamespace` lookalikes.
- Trade-offs:
  - Keeping human-readable strings in the canonical schema is convenient for prompts and rendering, but forces parsing logic everywhere.
  - Introducing canonical numeric fields increases schema complexity, but dramatically reduces execution risk and testing blind spots.

#### C2. Live close paths can mark positions closed in the journal before broker truth is known

- Confidence: High
- Impact: Live account and local journal can diverge; downstream P&L, reporting, and training attribution become untrustworthy
- Evidence:
  - `src/shadow_trading/executor.py` closes the local trade record before attempting `place_live_exit()` for live positions.
  - `src/main.py` manual live close prints `Closing journal record anyway.` when broker exit fails, then closes the local record regardless.
  - This affects both automated management and manual operator workflows.
- Root cause:
  - Journal state is being treated as the source of truth even on live exits, instead of broker-confirmed execution state.
- Recommendation:
  - Reverse the order of operations:
    - submit live exit,
    - confirm broker acceptance/fill state,
    - only then mark the journal closed.
  - If broker exit submission fails, keep the trade open locally and record an explicit reconciliation-needed state.
  - Add tests for broker-failure paths on automated and manual live exits.
- Trade-offs:
  - A broker-first model adds more intermediate states such as `exit_submitted` and `exit_pending`.
  - That added complexity is worth it; without it, the ledger cannot be trusted as an audit artifact.

#### C3. Several live-trading safety guards fail open on internal state-query errors

- Confidence: High
- Impact: Real-money trades can still be placed when daily-loss, duplicate, or max-position checks fail internally
- Evidence:
  - In `src/shadow_trading/executor.py`, live daily-loss, position-limit, and duplicate checks catch exceptions and continue.
  - Direct reproduction patched `get_open_shadow_trades()` to raise `Exception("db locked")`; `open_live_trade()` still submitted a live order and returned a trade id.
  - Logs during reproduction:
    - `Position limit check failed: db locked — continuing`
    - `Duplicate check failed: db locked — continuing`
- Root cause:
  - Fail-open error handling in safety-critical live paths.
- Recommendation:
  - Treat state-query failures as hard blockers in live trading.
  - For live paths, a broken safety check should mean `do not trade`.
  - Add explicit tests for DB-lock, query-failure, and stale-state scenarios.
- Trade-offs:
  - Fail-closed behavior will reduce availability during transient DB issues.
  - That is the correct trade for live capital. Availability is less important than bounded loss and auditability.

### High

#### H1. The council v2 migration broke public contracts, tests, and storage expectations

- Confidence: High
- Impact: Council subsystem is not trustworthy as a governed subsystem; session engine and tests diverged materially
- Evidence:
  - `tests/test_council_agents.py` fails at import time because legacy gather functions were removed from `src/council/agents.py`.
  - `tests/test_council.py` has 24 failing tests.
  - `run_round_1()` now assumes `_call_claude()` returns `(raw, debug)` and crashes when callers or tests provide a legacy plain-string return.
  - `run_round_2()` signature changed and `run_round_3()` no longer exists, but backward-compatible interfaces were not preserved.
  - `tally_votes()` no longer returns the legacy vote semantics expected by callers/tests.
  - `CouncilEngine.get_session()` now returns a flattened dict rather than the historical `{session, votes}` shape.
  - `is_devils_advocate` is hardcoded to `0`, so old storage semantics are gone even where the column still exists.
- Root cause:
  - A subsystem redesign shipped without a clean compatibility boundary or synchronized test migration.
- Recommendation:
  - Pick one of two explicit strategies:
    - finish the v2 migration and rewrite all tests/callers/documentation around the new contract, or
    - restore a real compatibility facade that preserves the v1 interfaces.
  - Do not keep the system in a half-v1/half-v2 state.
- Trade-offs:
  - Full v2 cleanup is cleaner long-term, but requires coordinated updates across tests, storage assumptions, and UI consumers.
  - Compatibility shims reduce short-term churn, but prolong old abstractions if kept too long.

#### H2. Council specialist queries target the wrong database schema and often return empty context

- Confidence: High
- Impact: Even if council orchestration is fixed, multiple agents are currently flying partially blind
- Evidence:
  - `src/council/agents.py` queries `vix_term_structure` using `vix_close` and `date`, but `src/data_collection/vix_collector.py` creates columns `vix` and `collected_date`.
  - `src/council/protocol.py` also queries `vix_term_structure` using `vix_close` and `date`.
  - `src/council/agents.py` queries `shadow_trades.sector`, but `src/journal/store.py` does not define a `sector` column on `shadow_trades`.
  - Direct reproduction with a minimally valid repo-style database returned:
    - `No tactical data available.`
    - `No risk data available.`
    - `No macro data available.`
  - `build_shared_context()` also logged formatting failure when recommendation aggregates returned `None`.
- Root cause:
  - Council v2 data access was ported from an older schema/model of the system without reconciling current table definitions.
- Recommendation:
  - Introduce one schema-owned council data adapter layer that translates current repo tables into the council’s internal view.
  - Remove raw ad hoc SQL from council agents where possible.
  - Add a contract test suite that seeds repo-native schemas and asserts non-empty council context.
- Trade-offs:
  - An adapter layer adds one more abstraction.
  - It also creates exactly the boundary this subsystem is currently missing.

#### H3. Local `/shadow/close/{ticker}` can close live trades in the journal without sending any broker exit

- Confidence: High
- Impact: A local dashboard/API action can create false closed-state records for live positions
- Evidence:
  - `src/api/routes/shadow.py` finds any open trade by ticker, regardless of `source`.
  - It closes the journal record and updates recommendation fields.
  - It never calls `place_paper_exit()` or `place_live_exit()`.
- Root cause:
  - Route implements local bookkeeping only, but is mounted under an execution-shaped API surface.
- Recommendation:
  - Either restrict the route to paper trades only, or branch explicitly by `source` and require broker confirmation before closure.
  - Return a 409-style error when a live trade cannot be exited at the broker.
- Trade-offs:
  - Restricting the route is the safest quick fix.
  - Supporting both paper and live correctly is more useful, but requires the same broker-first state machine recommended in C2.

#### H4. Paper trades are recorded as open even when all Alpaca entry submissions fail

- Confidence: High
- Impact: Paper broker truth, local journal truth, and training data truth can diverge at trade entry
- Evidence:
  - In `src/shadow_trading/executor.py`, if both the bracket order and fallback simple order fail, the trade is still recorded locally as `status="open"` with `recording trade without Alpaca`.
  - `tests/test_live_trading.py::TestPaperSourceTagging::test_paper_trade_tagged_as_paper` explicitly codifies this behavior.
- Root cause:
  - The system prioritizes continuity of local trade simulation over broker-aligned paper execution truth.
- Recommendation:
  - Separate simulated/local-only trades from broker-submitted paper trades at the schema level.
  - If Alpaca is intended to be authoritative for paper execution, do not mark the trade open without a broker order.
  - If local simulation is intentional, store a distinct source/state such as `source="simulated"` or `submission_state="broker_failed_local_only"`.
- Trade-offs:
  - Preserving a local-only fallback keeps the training flywheel moving.
  - But without explicit labeling, the resulting data is contaminated and hard to trust.

### Medium

#### M1. The risk governor kill switch relies on a global ambient file path that contaminates tests and environments

- Confidence: High
- Impact: Stale workspace state can halt all trading unintentionally and makes tests environment-dependent
- Evidence:
  - `src/risk/governor.py` hardcodes `_HALT_FILE = "data/trading_halted"`.
  - A real `data/trading_halted` file exists in this workspace.
  - `tests/test_risk_governor.py` fails broadly unless `_HALT_FILE` is monkeypatched because the ambient file forces `"Emergency halt: trading is halted via kill switch"`.
- Root cause:
  - Global file-based state with no environment scoping or test isolation.
- Recommendation:
  - Inject halt state path via config or environment.
  - For tests, default to an isolated temp path.
  - Consider storing operator halt state in the database with provenance (`who`, `when`, `why`) instead of an ambient file.
- Trade-offs:
  - File flags are simple and restart-persistent.
  - Database-backed halt state is slightly heavier, but is far easier to audit and isolate.

#### M2. Watch-loop open-trade Telegram notifications use nonexistent `PositionSizing` fields

- Confidence: High
- Impact: Trade-open notifications are silently lost in the main watch loop
- Evidence:
  - `src/scheduler/watch.py` calls `notify_trade_opened()` with `packet.position_sizing.entry_price`, `stop_level`, `target_1`, and `shares`.
  - `src/schemas.py` defines `PositionSizing` with only:
    - `allocation_dollars`
    - `allocation_pct`
    - `estimated_risk_dollars`
  - Repo-wide search only found those nonexistent attributes in the watch loop.
  - The call is wrapped in a broad `try/except`, so the failure is only logged as a warning.
- Root cause:
  - Notification code was not updated when packet/position-sizing ownership changed.
- Recommendation:
  - Source notification parameters from parsed packet execution values or from the persisted `shadow_trades` row, not from `PositionSizing`.
  - Add an integration test for the watch-loop notification path.
- Trade-offs:
  - Pulling from persisted trade state is slightly later in the flow.
  - It is also much more stable and better aligned with what was actually submitted/opened.

### Low

#### L1. Feature-engine tests are date-sensitive and fail on non-business days

- Confidence: High
- Impact: Clean-shell CI reliability is lower than the repo implies
- Evidence:
  - `tests/test_features.py` constructs arrays of length `n` but indexes them with `pd.bdate_range(end=pd.Timestamp.today(), periods=n)`.
  - On Sunday 2026-03-29, those lengths diverged and the fixture failed before feature code executed.
- Root cause:
  - Test data generation depends on the current calendar date.
- Recommendation:
  - Freeze the fixture end date to a business day or generate the index first and size arrays from `len(dates)`.
- Trade-offs:
  - Deterministic fixtures are less “realistic” in a trivial sense.
  - They are much better tests.

#### L2. `src/main.py` exceeds its own size guardrail and remains an oversized orchestration hub

- Confidence: High
- Impact: Maintainability risk; contributor friction; higher regression probability during CLI changes
- Evidence:
  - `tests/test_main_refactor.py` asserts `main.py` must be under 1000 lines.
  - `src/main.py` is 1016 lines.
  - Related orchestration files are also very large:
    - `src/scheduler/watch.py`: 2611 lines
    - `src/api/cloud_app.py`: 1421 lines
- Root cause:
  - Operational growth is outrunning modularization.
- Recommendation:
  - Move command handlers into domain-specific modules and keep `main.py` focused on parser composition and dispatch.
  - Treat `watch.py` and `cloud_app.py` similarly; they are already beyond comfortable review size.
- Trade-offs:
  - Refactoring orchestration code creates short-term merge friction.
  - It also lowers long-term audit and safety cost substantially.

## Additional Technical Observations

These did not rise to tracked-issue level in this pass, but they are meaningful:

- Broad exception swallowing is still common in operator-facing and observability-heavy code paths. The codebase has improved from earlier bare `except: pass` patterns, but a large amount of control flow still treats errors as warnings and continues.
- The council subsystem is especially vulnerable to schema drift because it owns ad hoc SQL directly instead of consuming stable service-layer views.
- `reconcile_live_trades()` repairs some live drift after the fact, which is useful, but reconciliation should be a backstop, not the primary way correctness is restored.
- The repo’s largest files are now operational control planes. That is a warning sign in a trading system.

## Strategy, Business, and Technology Commentary

### 1. The stated moat and the current engineering reality are not yet aligned

The repo repeatedly says training data quality is the competitive moat. That is directionally right, but the codebase still permits several ways for data truth to degrade:

- paper trades can exist without broker submission
- live trades can be marked closed without broker confirmation
- validator tests do not exercise the real runtime schema
- council outputs and context are drifting from the underlying data model

A data moat is only real when contracts around data creation are stricter than the rest of the application. Right now, they are not.

### 2. The project is trying to scale organizational complexity before proving operational invariants

There is a lot of sophistication here:

- multi-agent council
- holdout validation
- A/B model evaluation
- live/paper dual execution
- multiple future desks
- heavy research ingestion
- 24/7 GPU scheduling

That ambition is impressive, but the system still lacks a few basic invariants:

- broker truth > journal truth > dashboard truth
- one canonical packet execution schema
- deterministic tests around critical risk and execution paths
- subsystem-level migration discipline

My advice: slow feature-surface expansion until those invariants are hard.

### 3. Operational architecture is still prototype-grade relative to the claimed reliability target

SQLite, large monolithic Python control files, and file-flag operator controls are reasonable for an aggressive prototype. They are not yet a strong fit for a 24/7 autonomous trading platform that wants to be auditable and capital-scalable.

This does not mean “rewrite everything now.” It means the next engineering phase should prioritize:

- correctness boundaries
- state-machine clarity
- contract tests
- broker/journal reconciliation discipline
- modularization of operator control planes

before launching more desks or broadening capital.

### 4. The council is strategically interesting, but it currently looks like architecture debt, not edge

The council concept may become valuable for governance, calibration, and structured founder overrides. In the current repo, though, it is a source of migration debt:

- test breakage
- storage drift
- query/schema drift
- unclear backward-compatibility policy

Until it is stable, it is more likely to consume engineering calories than create trading edge.

### 5. The business plan should treat execution integrity as investor-facing infrastructure

If the long-term path is family LP / outside capital, then execution truth and auditability are not implementation details. They are part of the product.

Before scaling capital, the system should be able to answer cleanly:

- Was this trade actually submitted?
- Was it actually filled?
- When exactly did we know that?
- Which downstream records were derived from broker-confirmed truth versus simulation?

That answer is not consistent enough yet.

## Recommended Priority Order

1. Fix packet execution schema ownership and validator compatibility.
2. Fix live broker/journal truth ordering and fail-open safety checks.
3. Decide whether paper execution is broker-authoritative or simulation-authoritative, then encode that explicitly.
4. Finish the council migration instead of leaving it half-compatible.
5. Isolate halt-state management from ambient filesystem state.
6. Reduce monolith size in `main.py`, `watch.py`, and `cloud_app.py`.

## Validation Appendix

Representative test commands used during the audit:

```bash
./.venv/Scripts/python.exe -m pytest tests/test_council.py -q
./.venv/Scripts/python.exe -m pytest tests/test_council.py tests/test_council_agents.py -q
./.venv/Scripts/python.exe -m pytest tests/test_risk_governor.py -q
./.venv/Scripts/python.exe -m pytest tests/test_features.py -q
./.venv/Scripts/python.exe -m pytest tests/test_main_refactor.py -q
./.venv/Scripts/python.exe -m pytest tests/test_live_trading.py tests/test_llm_validator.py tests/test_llm_client.py -q
./.venv/Scripts/python.exe -m pytest --collect-only -q --ignore=tests/test_council_agents.py
```

Representative direct reproductions:

- real `TradePacket` passed into `validate_llm_output()`
- `open_shadow_trade()` with a real packet and validation enabled
- `open_live_trade()` with safety-state queries patched to raise
- council data gathering against repo-native table definitions

## Final Assessment

This is a serious prototype with real intellectual energy behind it. It is not yet a system whose most important claims are protected by equally serious engineering boundaries.

The gap is fixable. The fastest route to making Halcyon meaningfully stronger is not another feature wave. It is making data truth, execution truth, and contract truth boringly reliable.
