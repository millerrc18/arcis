# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- S02 carry-forward inventory (GitHub side): `docs/research/old-platform-inventory.md` (full T1–T10 report), `docs/research/trial-ledger.csv` (13 configurations), `config/incumbent_v1.yaml` (UNRESOLVED — no definition extractable; legacy docs conclude BLOCKED). Key findings: 7 specs recommended for clean-room reimplementation (walk-forward R1–R8, CPCV, bracket math, regime engine, attribution schema, cost calibration, trials/DSR); model training cutoff 2026-04-28 (Qwen3-8B → halcyon-v1); Finnhub data flagged DO NOT REUSE; T3 reconciliation not performable GitHub-side (no decision records); freeze deferred pending local archive.
- S01 T1: Alpaca news preflight completed 2026-10-02 — paper keys valid, news access allowed, no volatile article fields, synthetic fixture in `tests/fixtures/news_page_1.json`.
- Repository scaffold: documentation set in place (`README.md`, `CLAUDE.md`, `CHANGELOG.md`), research docs moved to `docs/research/`, sprint files to `docs/sprints/`, reference architecture to `docs/reference-architecture.md`.
- S01 T3: tooling and CI — `pyproject.toml` (Python 3.12, `src/` layout), `uv.lock`, ruff/mypy/pytest config, `tools/check_ledger.py`, `tools/check_size.py`, `tools/check_hygiene.py`, `tools/checks.py`, `.github/workflows/ci.yml`; every check has failing-example tests.
- S01 T4: required/no-default `Config` (pydantic, secrets env-only), data-root guard (refuses repo and cloud-sync paths), vendored S&P 500 (503 symbols) and S&P 100 (101 symbols) from Wikipedia 2026-10-02, `arcis-recorder universe` daily immutable snapshots.
- S01 T5: `AlpacaNewsClient` — 50-symbol chunks, pagination, exponential backoff with `Retry-After`, client-side rate limits, `Date` header capture, typed errors (`AuthError`, `RateLimitError`, `ClientError`).
- S01 T6: append-only store — `data_root/articles/<symbol>/<YYYY-MM-DD>.jsonl` (raw JSON, deduped), atomic manifests, `verify()` (manifest recompute, duplicates, ordering).
- S01 T7: version hash (sha256 over canonical raw JSON; excluded-fields empty per T1), per-symbol tamper-evident index, `rebuild()`.
- S01 T8: `arcis-recorder poll` (*/15 cron, OS lock, universe validation, 300s clock check, atomic heartbeat), `sweep` (backfill), `gaps` (coverage report).
- S01 T9: 105 tests, 94% line coverage on `src/arcis/recorder/`; live smoke passed in full and fingerprint modes.
- S01 T10: `docs/runbooks/news-recorder.md` operator runbook (install, cron, failure modes, D-018 rights reversal).
