# S09-structural-code — E1+E3: odd-lot tender engine and reconstitution monitor

Branch: `feat/oddlot-code-v2`. Follows charter PR #14 (D-039) and docs PR #15
(D-033–D-037), which must merge first per §6.2.

Status: in progress — addressing Claude Code REJECT on PR #13.

## Goal

Build the E1 (odd-lot tender engine) and E3 (reconstitution monitor) code
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

### E3: Reconstitution monitor (`src/arcis/reconstitution/`)
- [x] Migration classification (downward, deletion_rebound)
- [x] Strict deletion rule (requires explicit "none", not empty string)
- [x] December 2026 schedule and checklist

### Tests
- [x] 28 tests passing (15 oddlot + 13 recon)
- [x] New tests for checklist gates and strict validation

## Out of scope
- Actual LLM API integration (prompt builder only; caller supplies model)
- Live EDGAR polling (manual scan only; cron setup separate)
- December 2026 preliminary list fetching (starts Nov 13)

## Deviations
- Branch renamed from `feat/oddlot-engine` to `feat/oddlot-code-v2` to
  reflect the three-PR split (charter, docs, code).
- `OppStatus` changed from `str, Enum` to `StrEnum` (ruff UP042).
