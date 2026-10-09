# S09-structural-code — E1: odd-lot tender engine

Branch: `feat/oddlot-code-v2`. Follows charter PR #17 (D-039) and docs PR #18
(D-033–D-037), which must merge first per §6.2.

Status: in progress — addressing Claude Code REJECT on PR #19.

## Deviations

E3 (reconstitution monitor) removed from this sprint. D-039 sets `reconstitution`
to Active = no until E2's done-means is met. The `src/arcis/reconstitution/`
package and `tests/test_recon.py` are deferred to a sprint after E2.

## Goal

Build the E1 (odd-lot tender engine) code
per the D-039 charter amendment. Done when:
- EDGAR SC TO-I ingestion polls daily with typed errors (not swallowed),
  paginates through all results, and filters amendments
- LLM offer-document reader uses strict schema validation (rejects truthy
  strings, wrong types, unknown keys)
- Pre-trade checklist is fail-closed (missing data = failure, costs applied,
  threshold checked) and gates the VETTED transition
- Reconstitution monitor classifies migrations correctly (no empty-string
  deletions)
- All checks pass: ruff, mypy --strict, size-src, pytest, ledger

## Tasks

### E1: Odd-lot engine (`src/arcis/oddlot/`)
- [x] EDGAR client with typed errors (EdgarConfigError, EdgarNetworkError,
      EdgarParseError)
- [x] Pagination via EFTS `from`/`size` parameters
- [x] Amendment filtering (exclude /A forms)
- [x] Tight odd-lot regex patterns (remove boilerplate matches)
- [x] Fail-closed User-Agent config (ARCIS_SEC_USER_AGENT env var)
- [x] Strict LLM schema validation (reject "false" string, wrong types)
- [x] Fail-closed checklist (costs applied, threshold checked, missing= fail)
- [x] Lifecycle gates (VETTED requires passed checklist)
- [x] Expiry check: fail on ≤2 days (not warning)

### E3: Reconstitution monitor — DEFERRED (see Deviations above)

### Tests
- [x] 15 oddlot tests passing
- [x] New tests for checklist gates and strict validation

## Sprint report

Built the E1 odd-lot tender engine per D-039: EDGAR SC TO-I ingestion with
typed errors and fail-closed pagination, LLM offer-document reader with
strict schema validation, and a pre-trade checklist that fails closed on
missing data. The cost model is UNRESOLVED (no sourced broker fee schedule)
so the checklist always fails until it's sourced. E3 (reconstitution) was
removed from this sprint (see Deviations) because D-039 sets it to Active=no
until E2's done-means is met.

## Out of scope
- Actual LLM API integration (prompt builder only; caller supplies model)
- Live EDGAR polling (manual scan only; cron setup separate)
- E3 reconstitution monitor (deferred to post-E2 sprint)

## Deviations
- Branch renamed from `feat/oddlot-engine` to `feat/oddlot-code-v2` to
  reflect the three-PR split (charter, docs, code).
- `OppStatus` changed from `str, Enum` to `StrEnum` (ruff UP042).
- E3 removed: `src/arcis/reconstitution/` and `tests/test_recon.py` deleted.
  D-039 (merged) sets `reconstitution` to Active=no until E2 done-means met.
