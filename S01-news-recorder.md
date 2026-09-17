# S01 — Forward News Recorder

| | |
|---|---|
| **Branch** | `feat/s01-news-recorder` |
| **Repository** | New, empty repository. The old repository is read-only reference; do not copy code from it. |
| **Depends on** | `SCOPE.md` and `PREREGISTRATION.md` committed at the repo root (drafts are fine) |
| **Ledger row** | `recorder`: CORE, Step 1, Active (SCOPE.md §3.1) |
| **Invariants** | I-6 fail-closed config · I-7 storage location · I-10 single instance · I-12 no blind exception handling · I-13 no retained article text without written rights |
| **Research refs** | Research log R08 (feed reliability and terms) |
| **Settled before hand-off** | Capture universe: current S&P 500 constituents (SCOPE D-011). Storage mode: fingerprint (SCOPE D-010) |
| **Tasks** | 10 |

## Why this sprint exists

The most important open question (does the LLM add value?) can only be answered cleanly on data captured after a model's training cutoff, and that data accumulates at calendar speed. Alpaca's archive can re-serve old articles, but each article carries only a created and an updated time, with no version history. The archive cannot prove which version existed at a given moment, or when we could first see it. This recorder produces that proof: every article version for the capture universe, with our own first-seen timestamp.

Alpaca's public terms do not clearly allow keeping article text, so the recorder starts in **fingerprint mode**. It stores each version's metadata and hashes, not its headline, summary, or body. If Alpaca later confirms the rights in writing, text can be recovered by re-querying the archive and keeping only versions whose hashes match the fingerprints, and full-text storage can be switched on.

The capture universe is the S&P 500 (which contains every S&P 100 name). The research universe is still an open decision, and forward capture cannot be added retroactively.

## Hard scope

**In:** polling Alpaca's news endpoint for the capture universe; append-only fingerprint storage; a derived version index; integrity verification; gap reporting; a heartbeat; a runbook; the repo skeleton and CI.

**Out:** retaining article headline, summary, or body text (except when `storage.retain_text` is true, which requires Alpaca's written confirmation first); any scoring (FinBERT or LLM); text recovery from the archive; prices; EDGAR; databases beyond the derived index; websockets; dashboards; cloud deployment; alerting beyond the heartbeat; automated universe maintenance; backfilling history from before the first poll.

If a task appears to need anything from **Out**, stop and write it up in the sprint report instead of building it.

## Known API facts (checked against Alpaca's docs on 2026-09-16; T1 re-verifies)

- `GET https://data.alpaca.markets/v1beta1/news`, authenticated with the `APCA-API-KEY-ID` and `APCA-API-SECRET-KEY` headers.
- Query parameters: `start` and `end` (RFC-3339 or `YYYY-MM-DD`, inclusive); `sort` (`asc` or `desc`, ordered by updated time, default `desc`); `symbols` (comma-separated); `limit` (1–50); `include_content`; `exclude_contentless`; `page_token`.
- Article fields: `id` (int), `headline`, `summary`, `author`, `created_at`, `updated_at` (RFC-3339), `content` (may contain HTML), `url`, `symbols` (array), `source`, `images`.
- HTTP 429 means rate limited, with `X-RateLimit-*` headers. 401 or 403 means an authentication or permission problem.
- Plan material describes 200 requests per minute on the Basic plan. Treat this as a vendor claim; T1 records the actual headers.
- For users without real-time access, the default window ends at least 15 minutes in the past.
- The archive reaches back to 2015. Benzinga is the only source.

**Unknown until T1:** the REST response envelope (expected: `news` and `next_page_token`); whether `start` and `end` filter on `created_at` or `updated_at`; whether this account's plan allows news access at all; the account's rate limit; whether any article field changes between identical requests.

---

## Tasks

Unit tests ship with each task, not in a batch at the end.

### T1 — Live preflight (gates everything else)

Using the **paper-account** keys (least privilege), request three large-cap symbols over the last 24 hours with `include_content=true`. Then repeat the identical request. Inspect both responses **in memory only**; do not write response bodies to disk anywhere.

Record in the sprint report:

1. The HTTP status. **If it is 401 or 403, stop the sprint after T1** and report. Do not implement another source (SCOPE OD-5).
2. The response envelope keys and pagination behavior.
3. The `X-RateLimit-*` header values.
4. A field-by-field comparison of the two identical responses. Any field that differs is **volatile** and must be excluded from the version hash (T7). List them.
5. Filter semantics: is an article with `created_at` before `start` but `updated_at` after it returned? If no such article can be found, say so; the design works either way.
6. Field names and types only (no text values) for the fixture.

Build a synthetic test fixture with the same shape and invented text for `tests/fixtures/`.

**Done when:** the report section exists, no response body was persisted, and, if access works, the synthetic fixture is committed.

### T2 — Repository skeleton and CI

- Python 3.12; `src/arcis/` layout; `uv` with a committed lock file.
- Runtime dependencies: `httpx`, `pydantic` (v2), `pyyaml`. Test dependencies: `pytest`, `pytest-cov`, `respx`. Add nothing else without a justification in the sprint report.
- `ruff` (with the `BLE` blind-except rules enabled), `mypy --strict` on `src/`, and `pytest`.
- `tools/check_ledger.py`: parses the SCOPE.md §3.1 and §3.2 tables and fails if any subpackage of `src/arcis/` is not listed there with Active = yes.
- `tools/check_size.py`: fails on any `src/` file over 400 lines or any function over 60 lines (using `ast`).
- A GitHub Actions workflow runs all of the above on every push and pull request.
- `.gitignore` covers `.env` files and any local data directories.

**Done when:** CI is green on the skeleton, and each check has a test proving it fails on a deliberately bad example.

### T3 — Configuration and secrets (I-6)

- `config/recorder.yaml` loads into a pydantic model with `extra="forbid"` and **no field defaults**.
- Fields: `data_root`, `universe_file`, `storage.retain_text`, `poll.lookback_hours`, `sweep.lookback_hours`, `http.timeout_seconds`, `http.max_retries`, `http.symbols_per_request`, `http.page_limit` (≤ 50), `clock.warn_skew_seconds`, `clock.max_skew_seconds`, `heartbeat.enabled`, `gaps.max_gap_minutes`.
- Secrets come from the environment only: `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, and `ARCIS_HEARTBEAT_URL` (required only when `heartbeat.enabled` is true).
- A missing key, unknown key, invalid value, or missing required secret exits non-zero with a message naming the problem. Secret values are never logged.
- Initial values: `storage.retain_text: false`, `poll.lookback_hours: 2`, `sweep.lookback_hours: 72`, `http.symbols_per_request: 50`, `http.page_limit: 50`, `clock.warn_skew_seconds: 5`, `clock.max_skew_seconds: 60`, `gaps.max_gap_minutes: 30`.

**Done when:** tests cover every failure mode listed above.

### T4 — Data-root guard and universe (I-7)

**Data-root guard**, run at startup before any other I/O:

- Resolve `data_root` to an absolute path.
- Refuse it if it is inside the git working tree.
- Refuse it if it is inside a cloud-sync folder: anywhere under the directories named by the `OneDrive`, `OneDriveConsumer`, or `OneDriveCommercial` environment variables, or any path with a segment containing `OneDrive`, `Dropbox`, `Google Drive`, or `iCloudDrive` (case-insensitive).
- Create `raw/news/alpaca/`, `index/`, `logs/`, and `locks/` under it if they are missing.

**Universe:** `config/universe.csv` with columns `symbol,name,in_sp100,as_of,source`. Populate it with the current S&P 500 constituents, flag the S&P 100 members, and record the source and date. The indexes can hold more securities than their names suggest because of dual share classes; include every listed security. The loader rejects empty files, duplicate symbols, lowercase or whitespace-padded symbols, invalid booleans, and invalid dates. Membership changes are manual edits with a CHANGELOG entry.

**Done when:** guard and loader tests pass, including a OneDrive-path refusal and a repo-path refusal.

### T5 — Alpaca news client (I-12)

`src/arcis/recorder/client.py`:

- `iter_news(symbols, start, end)` yields pages, following the pagination token found in T1 until it is exhausted, with `include_content=true` (needed for the hashes), `sort=asc`, and `limit` set from `http.page_limit`.
- The universe is split into chunks of `http.symbols_per_request` (about 10 chunks for the S&P 500).
- Retries use exponential backoff with jitter on 429, 5xx, and timeouts, up to `http.max_retries`. When rate-limit headers show zero requests remaining, wait until the reset time.
- Typed errors: `AuthError` (401/403, never retried), `BadRequestError` (400), `RateLimitError` (retries exhausted), `UpstreamError` (5xx or timeouts, retries exhausted).
- Each response's `Date` header is captured for the clock check (T8).
- A descriptive `User-Agent` is set. Headers and response bodies are never logged.

**Done when:** tests cover pagination, each error class, retry exhaustion, and rate-limit waits. The sleep function is injected so tests run instantly.

### T6 — Append-only store

`src/arcis/recorder/store.py`:

- Layout: `raw/news/alpaca/YYYY/MM/YYYY-MM-DD.jsonl`, partitioned by the **UTC date of `fetched_at`**.
- One line per newly seen article version:

  ```json
  {"schema": "news_obs.v2", "fetched_at": "<UTC RFC-3339 with microseconds>", "server_date": "<HTTP Date header>", "poll_id": "<uuid4>", "mode": "poll|sweep|override", "storage_mode": "fingerprint|full", "version_sha256": "<hex>", "text_sha256": {"headline": "<hex or null>", "summary": "<hex or null>", "content": "<hex or null>"}, "item": {"...": "see below"}}
  ```

- `text_sha256` holds the SHA-256 of each field's exact UTF-8 string, or null if the field is absent.
- In fingerprint mode (`storage.retain_text: false`), `item` is the article as received **with `headline`, `summary`, and `content` removed**. In full mode, `item` is the article exactly as received.
- Each write appends the line and a newline, then flushes and calls `fsync`.
- **Sealing:** at the start of every run, each unsealed file for a UTC date before today gets a manifest, `YYYY-MM-DD.manifest.json` (`lines`, the file's `sha256`, and the first and last `fetched_at`), and is set read-only. The writer refuses to touch a sealed date.
- `verify [--date D]` recomputes file hashes against manifests and validates every line against the schema. It recomputes `version_sha256` only for records stored in full mode. Any mismatch exits non-zero.

**Done when:** tests prove append behavior; refusal on a sealed date; manifest correctness; that `verify` catches a single altered byte; and that fingerprint-mode lines contain no `headline`, `summary`, or `content` keys.

### T7 — Version index

- `version_sha256` is the SHA-256 of the **complete** article's canonical JSON (sorted keys, compact separators, UTF-8), computed **before** any text is removed and **excluding the volatile fields found in T1**. The excluded fields are a named constant in code and are listed in the sprint report.
- A derived SQLite index at `index/news_versions.sqlite` (WAL mode) holds `versions(article_id INTEGER, version_sha256 TEXT, updated_at TEXT, first_fetched_at TEXT, file TEXT, PRIMARY KEY (article_id, version_sha256))`.
- A version is written to the store only if its key is not already indexed.
- Order of operations: append the line (with `fsync`), then insert the index row. If the process dies between the two, the next run appends a duplicate line with a later `fetched_at`. That is acceptable, because the index always keeps the **earliest** `fetched_at`.
- `rebuild-index` recreates the index from the stored lines alone and must produce identical rows.

**Done when:** tests cover a repeated article (one line), a changed article with the same `id` (two versions), a change to text only (a new version, even in fingerprint mode), the crash-between-writes case, and rebuild equivalence.

### T8 — `poll`, `sweep`, and `gaps` commands (I-10)

`python -m arcis.recorder poll` and `python -m arcis.recorder sweep` differ only in lookback (`poll.lookback_hours` versus `sweep.lookback_hours`). For manual recovery after a long outage, `sweep --lookback-hours N` overrides the lookback and is logged with `mode: override`.

Each run:

1. Takes an **OS-level exclusive lock** on `locks/recorder.lock` (`msvcrt` on Windows, `fcntl` elsewhere), held for the life of the process so it releases automatically if the process dies. If the lock is held, log `skipped: another instance running` and exit 0 without a heartbeat.
2. Validates config, secrets, data root, and universe, and logs the storage mode.
3. Seals any past-date files (T6).
4. Requests the window `[now − lookback, now]` for every symbol chunk.
5. **Clock check:** compares local UTC time with each response's `Date` header. A skew above `clock.warn_skew_seconds` logs a warning. A skew above `clock.max_skew_seconds` aborts the run before anything is written, because `fetched_at` is the evidence and an untrustworthy clock is a failure.
6. Writes new versions (T6, T7).
7. Appends one line to `logs/polls.jsonl`: `poll_id`, `mode`, `storage_mode`, start and end times, status, articles seen, new versions, pages, requests, rate-limit remaining, and maximum clock skew.
8. On success, pings `ARCIS_HEARTBEAT_URL`. On failure, pings `<url>/fail`, logs the typed error, and exits 1.

The only broad exception handler allowed is at the CLI entry point. It must log, send the failure ping, and exit non-zero, with one `noqa: BLE001` and a justification comment.

**`gaps --since D`** reads `logs/polls.jsonl`, lists every interval longer than `gaps.max_gap_minutes` without a successful run of any mode, and exits non-zero if any exist.

**Done when:** an end-to-end test with mocked HTTP produces the expected files, index rows, poll-log line, and heartbeat call in both storage modes; failure-path and lock-contention tests pass; and the clock-skew abort is tested with an injected clock.

### T9 — Coverage and live smoke test

- Every test from T2–T8 runs offline against synthetic fixtures.
- Line coverage for `src/arcis/recorder/` is at least 90%.
- One live test, marked `live`, is skipped unless `ARCIS_LIVE_TESTS=1` and both Alpaca keys are set. It runs `poll` in fingerprint mode into a temporary data root, then `verify`, then confirms that no headline returned by the API appears anywhere in the stored files. Run it once before opening the PR, paste its poll-log line into the sprint report, and delete the temporary data root.

**Done when:** the offline suite is green in CI, and the live result is recorded (or the report states plainly that keys were unavailable).

### T10 — Documentation

- `README.md`: what the repo is, how to install it, how to run the checks, and a pointer to SCOPE.md.
- `docs/runbooks/recorder.md`:
  - Setting the environment variables on Windows (user scope).
  - Windows Task Scheduler: `poll` every 10 minutes, and `sweep` daily at a fixed early-morning local time. Use "run whether user is logged on or not," "do not start a new instance," and "wake the computer to run this task." Include a `Register-ScheduledTask` PowerShell snippet for each.
  - Healthchecks.io: one check with a 10-minute period and a 20-minute grace period.
  - Daily operator check: `gaps --since <yesterday>` and `verify`.
  - Recovery: `sweep` recovers up to 72 hours of missed articles, and their `fetched_at` honestly shows the late capture. For longer outages, use `sweep --lookback-hours N`.
  - **Storage mode:** why the recorder starts in fingerprint mode; that switching to full mode requires Alpaca's written confirmation recorded in SCOPE.md §9 first; and that versions captured in fingerprint mode can only be recovered later by re-querying the archive and matching `version_sha256`.
  - Where the data lives, and why it must stay outside the repo and outside sync folders.
- `CHANGELOG.md`: first entry.
- `SCOPE.md`: update D-004 with the preflight result.
- The sprint report, appended below: what was built, deviations and why, T1 findings, the volatile-field list, and open issues.

**Done when:** a new reader could install, configure, schedule, and verify the recorder from the runbook alone.

---

## Acceptance criteria

1. T1 findings are recorded, and no response body was persisted. If access was refused, the sprint ends after T1 and nothing else merges.
2. CI is green: ruff, mypy, pytest (with ≥ 90% coverage on `recorder`), the ledger check, and the size check.
3. No `src/` file exceeds 400 lines, and no function exceeds 60 lines.
4. Exactly one broad exception handler exists, at the CLI entry point, with a justification.
5. In fingerprint mode, no stored file contains article headline, summary, or body text (proved by tests and by the live smoke check).
6. The live smoke result is recorded, or its absence is stated.
7. Nothing from **Out** appears in the diff.
8. `recorder` is the only subpackage under `src/arcis/`.

## After merge (Ryan)

1. Set the three environment variables on the host.
2. Register both scheduled tasks from the runbook.
3. Create the Healthchecks.io check.
4. After 7 days with `gaps` clean and `verify` passing, Step 1 is done (SCOPE.md §5).

## Sprint report

_(Claude Code appends here.)_

---

## Ralph Loop log (spec review before hand-off)

**Pass 1 — draft.** Scope, API facts from Alpaca's docs, and ten tasks with a preflight gate.

**Pass 2 — gap review.** Found and fixed:

1. Re-reading a 24-hour window with full content every 10 minutes would download on the order of 100 MB a day. Split into a 2-hour `poll` plus a daily 72-hour `sweep`.
2. A field that changes on every request would make every poll look like a new version. T1 now identifies volatile fields, and T7 excludes them from the hash.
3. `fetched_at` is only as trustworthy as the host clock. Added the server `Date` header check, with an abort threshold.
4. Test fixtures would have committed real Benzinga content. Fixtures are now synthetic.
5. File-based locks go stale after a crash. Replaced with an OS-level lock that releases when the process dies.
6. The ledger check would have allowed live-lane packages to appear early. SCOPE.md now has an Active column, and CI enforces it.
7. A crash between the append and the index insert was undefined. Defined as a tolerated duplicate, with the earliest `fetched_at` winning, plus a rebuild-equivalence test.
8. There was no path for outages longer than 72 hours. Added `sweep --lookback-hours` as an override that is logged as such.

**Pass 3 — polish.** Added a "done when" to every task, moved secrets to environment-only, capped dependencies, made the 401/403 path an explicit stop, and required tests to ship with each task rather than at the end.

**Pass 4 — research-log revision (R08).**

1. Public terms do not clearly allow retaining article text. Added fingerprint mode as the default, with per-field text hashes, and made full-text storage an explicit, rights-gated switch.
2. The version hash must still detect text-only revisions. It is now computed on the complete article before text is removed, with a test for text-only changes.
3. T1 would have saved raw responses to disk. It now inspects them in memory only.
4. The research universe is undecided, and forward capture cannot be added later. The capture universe is now the S&P 500, with S&P 100 members flagged, which fits comfortably within the documented rate limit.
5. `verify` cannot recompute a version hash without text. It now validates schema and file hashes in fingerprint mode and recomputes version hashes only for full-mode records.
