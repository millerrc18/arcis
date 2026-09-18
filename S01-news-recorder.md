# S01 — Repository Foundation and Forward News Recorder

| | |
|---|---|
| **Branch** | `feat/s01-news-recorder` |
| **Repository** | `millerrc18/arcis` (public). The old repository is read-only reference; do not copy code from it. |
| **Depends on** | SCOPE.md and PREREGISTRATION.md present at the repo root (drafts are fine) |
| **Ledger row** | `recorder`: CORE, Step 1, Active (SCOPE.md §3.1) |
| **Invariants** | I-6 fail-closed config · I-7 storage location · I-10 single instance · I-12 no blind exception handling · I-13 no retained article text without written rights · I-16 nothing private in a public repo |
| **Research refs** | Research log R08 (feed reliability and terms) |
| **Settled before hand-off** | Capture universe: current S&P 500 constituents (SCOPE D-011, D-012). Storage mode: fingerprint (SCOPE D-010) |
| **Tasks** | 10 |

## Why this sprint exists

Two jobs, and they belong together because the second one has to land inside a structure that will still make sense in a year.

**The repository foundation.** Everything after this sprint is built by agent sessions working from documents. The repo has to explain itself: what it is, what is in scope, what counts as evidence, how work is done, and what must never be committed. That is the difference between a project that stays legible and one that quietly sprawls.

**The forward news recorder.** The most important open question, whether the LLM adds value, can only be answered cleanly on data captured after a model's training cutoff, and that data accumulates at calendar speed. Alpaca's archive can re-serve old articles, but each carries only a created and an updated time, with no version history. It cannot prove which version existed at a given moment, or when we could first see it. This recorder produces that proof: every article version for the capture universe, with our own first-seen timestamp.

Alpaca's public terms do not clearly allow keeping article text, so the recorder starts in **fingerprint mode**: each version's metadata and hashes, never its headline, summary, or body. If Alpaca confirms the rights in writing, text can be recovered later by re-querying the archive and keeping only versions whose hashes match, and full-text storage becomes a config switch.

The capture universe is the S&P 500, which contains every S&P 100 name. Forward capture cannot be added retroactively, and the daily universe snapshot this sprint writes is now the project's only point-in-time membership record (SCOPE D-013).

## Hard scope

**In:** repository scaffold, documentation set, tooling and CI checks; polling Alpaca's news endpoint for the capture universe; append-only fingerprint storage; a derived version index; integrity verification; gap reporting; a heartbeat; a runbook.

**Out:** retaining article headline, summary, or body text (except when `storage.retain_text` is true, which requires Alpaca's written confirmation first); any scoring (FinBERT or LLM); text recovery from the archive; prices; EDGAR; databases beyond the derived index; websockets; dashboards; cloud deployment; alerting beyond the heartbeat; automated universe maintenance; backfilling history from before the first poll; any package other than `recorder`.

If a task appears to need anything from **Out**, stop and write it up in the sprint report instead of building it.

## Target layout

```
arcis/
├── README.md                  entry point and documentation map
├── CLAUDE.md                  rules every agent session reads first
├── SCOPE.md                   the boundary: ledger, invariants, decisions
├── PREREGISTRATION.md         what counts as evidence
├── CHANGELOG.md
├── pyproject.toml
├── uv.lock
├── .python-version
├── .gitignore
├── .github/
│   ├── workflows/ci.yml
│   └── pull_request_template.md
├── config/
│   ├── recorder.yaml
│   └── universe.csv
├── docs/
│   ├── reference-architecture.md
│   ├── research/
│   │   ├── RESEARCH-QUESTIONS.md
│   │   └── research-log.md
│   ├── runbooks/
│   │   └── recorder.md
│   └── sprints/
│       ├── S01-news-recorder.md
│       └── S02-carry-forward-inventory.md
├── src/arcis/recorder/
├── tests/
│   └── fixtures/
└── tools/
    ├── checks.py              runs every check locally, same as CI
    ├── check_ledger.py
    ├── check_size.py
    └── check_hygiene.py
```

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

Using the **paper-account** keys (least privilege), request three large-cap symbols over the last 24 hours with `include_content=true`. Then repeat the identical request. Inspect both responses **in memory only**; never write a response body to disk.

Record in the sprint report:

1. The HTTP status. **If it is 401 or 403, stop the sprint after T1** and report. Do not implement another source (SCOPE OD-5).
2. The response envelope keys and pagination behavior.
3. The `X-RateLimit-*` header values.
4. A field-by-field comparison of the two identical responses. Any field that differs is **volatile** and must be excluded from the version hash (T7). List them.
5. Filter semantics: is an article with `created_at` before `start` but `updated_at` after it returned? If no such article can be found, say so; the design works either way.
6. Field names and types only, with no text values, for the fixture.

Build a synthetic fixture with the same shape and invented text in `tests/fixtures/`.

**Done when:** the report section exists, no response body was persisted, and, if access works, the synthetic fixture is committed.

### T2 — Repository scaffold and documentation set

Create the layout above, and move what is already in the repo into place: `RESEARCH-QUESTIONS.md` to `docs/research/`, the sprint files to `docs/sprints/`, the research log to `docs/research/research-log.md`, and the reference architecture to `docs/reference-architecture.md`. SCOPE.md, PREREGISTRATION.md, README.md, CLAUDE.md, and CHANGELOG.md stay at the root.

**`README.md`** is the entry point for a reader who knows nothing. Sections, in this order:

1. **What this is.** A personal research project testing whether a long-only pullback strategy on the point-in-time S&P 500 has an edge worth trading. Not a product, not advice, no capital at risk today.
2. **Status.** Which step of SCOPE.md §5 is current, what exists, and what deliberately does not exist yet.
3. **Documentation map.** A table of every document, what question it answers, and when to read it: SCOPE.md (what is in scope, and what each component must do), PREREGISTRATION.md (what counts as evidence and what decides each question), `docs/research/research-log.md` (the outside evidence behind those choices), `docs/research/RESEARCH-QUESTIONS.md` (open questions and their prompts), `docs/sprints/` (units of work), `docs/runbooks/` (how to operate what is running), `CLAUDE.md` (rules for agent sessions), `CHANGELOG.md` (what changed).
4. **Quickstart.** Install with `uv`, run every check with one command, configure the recorder, run one poll, run `verify`.
5. **Where the data lives.** Outside the repository, outside any cloud-sync folder, and why both matter (I-7).
6. **What this repository never contains.** Credentials, market data, news article text, personal records (I-13, I-16). The repository is public.
7. **How decisions get made.** A short pointer to SCOPE.md §6: nothing is built without a ledger row, and every proposal names the gate it moves.
8. **Disclaimer.** Personal research, no investment advice, no warranty.

Keep it under roughly 150 lines. It points at the other documents rather than repeating them.

**`CLAUDE.md`** is what an agent session reads before touching anything. It states:

- Read SCOPE.md first. The ledger in §3 is the boundary; if a component is not listed as CORE and Active, it does not get built.
- Work only the tasks in the current sprint file. If something seems to need work outside the sprint's scope, stop and write it in the sprint report.
- Never invent a value, a rule, or a result. Record it as `UNRESOLVED` and ask.
- Code rules: Python 3.12, no source file over 400 lines, no function over 60 lines, no blind exception handling, typed errors, fail-closed configuration, tests with every task.
- Never commit credentials, market data, news article text, personal records, or large binaries. The repository is public.
- Branch naming `feat/sNN-slug`, one sprint per branch, the PR template checklist must pass, and every sprint updates the README documentation map (if it added a document), the CHANGELOG, and its own sprint report.
- Run `uv run python tools/checks.py` before opening a PR; it runs exactly what CI runs.

**`CHANGELOG.md`** follows Keep a Changelog, starting with an `Unreleased` section.

**`.github/pull_request_template.md`** carries a checklist: sprint and task list; ledger row exists and is Active; checks pass locally; no file over 400 lines and no function over 60 lines; nothing from the sprint's Out list in the diff; no credentials, data, article text, or personal records added; documentation map, CHANGELOG, and sprint report updated; any `# hygiene: allow` pragma justified.

**`.gitignore`** covers `.env*`, virtual environments, caches, `*.sqlite*`, and any local data directory.

**Done when:** the layout matches, every moved file is in place with no duplicates left behind, and README and CLAUDE.md are written as specified.

### T3 — Tooling, checks, and CI

- `pyproject.toml` for Python 3.12 with a `src/` layout. Runtime dependencies: `httpx`, `pydantic` (v2), `pyyaml`. Test dependencies: `pytest`, `pytest-cov`, `respx`. Add nothing else without a justification in the sprint report. Commit `uv.lock`.
- Tool configuration in `pyproject.toml`: `ruff` (including the `BLE` blind-except rules), `mypy --strict` for `src/`, `pytest` with coverage.
- `tools/check_ledger.py`: parses the SCOPE.md §3.1 and §3.2 tables and fails if any subpackage of `src/arcis/` is missing there or is not marked Active.
- `tools/check_size.py`: fails on any `src/` file over 400 lines or any function over 60 lines, using `ast`.
- `tools/check_hygiene.py`: fails if a tracked file has a data extension (`.jsonl`, `.parquet`, `.db`, `.sqlite`, `.gguf`, `.safetensors`, `.pkl`, `.zip`) or is a `.csv` outside `config/` and `docs/research/`; if any tracked file exceeds 1 MB; if the sprint file naming pattern `S\d\d-[a-z0-9-]+\.md` is broken; or if any tracked file contains a credential-shaped string (Alpaca-style key IDs, assigned API keys or secrets, private-key blocks, ping URLs with UUIDs). A line ending in `# hygiene: allow` or `<!-- hygiene: allow -->` is skipped, and the PR template requires justifying each one.
- `tools/checks.py` runs ruff, mypy, the three checks, and pytest in one command.
- `.github/workflows/ci.yml` runs `tools/checks.py` on every push and pull request.
- Each check has a test proving it fails on a deliberately bad example.

**Done when:** CI is green on the scaffold and every check has a failing-example test.

### T4 — Configuration, data-root guard, universe, and daily snapshot

**Configuration (I-6).** `config/recorder.yaml` loads into a pydantic model with `extra="forbid"` and **no field defaults**. Fields: `data_root`, `universe_file`, `storage.retain_text`, `poll.lookback_hours`, `sweep.lookback_hours`, `http.timeout_seconds`, `http.max_retries`, `http.symbols_per_request`, `http.page_limit` (≤ 50), `clock.warn_skew_seconds`, `clock.max_skew_seconds`, `heartbeat.enabled`, `gaps.max_gap_minutes`. Initial values: `storage.retain_text: false`, `poll.lookback_hours: 2`, `sweep.lookback_hours: 72`, `http.symbols_per_request: 50`, `http.page_limit: 50`, `clock.warn_skew_seconds: 5`, `clock.max_skew_seconds: 60`, `gaps.max_gap_minutes: 30`.

Secrets come from the environment only: `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, and `ARCIS_HEARTBEAT_URL` (required only when `heartbeat.enabled` is true). A missing key, unknown key, invalid value, or missing required secret exits non-zero with a message naming the problem. Secret values are never logged.

**Data-root guard (I-7),** before any other I/O: resolve `data_root`; refuse it if it is inside the git working tree; refuse it if it is inside a cloud-sync folder (anywhere under the directories named by the `OneDrive`, `OneDriveConsumer`, or `OneDriveCommercial` environment variables, or any path with a segment containing `OneDrive`, `Dropbox`, `Google Drive`, or `iCloudDrive`, case-insensitive); then create `raw/news/alpaca/`, `raw/universe/`, `index/`, `logs/`, and `locks/`.

**Universe.** `config/universe.csv` with columns `symbol,name,in_sp100,as_of,source`, populated with current S&P 500 constituents, S&P 100 members flagged, and the source and date recorded. Include every listed security, since dual share classes make the count exceed the index name. The loader rejects empty files, duplicate symbols, lowercase or whitespace-padded symbols, invalid booleans, and invalid dates. Membership changes are manual edits with a CHANGELOG entry.

**Daily snapshot.** On the first successful run of each UTC day, copy the parsed universe to `raw/universe/YYYY-MM-DD.csv` (skip if present) and record its SHA-256 in the poll log. These snapshots are the project's only point-in-time membership record (SCOPE D-013).

**Done when:** tests cover every configuration failure mode, a OneDrive-path refusal, a repo-path refusal, the loader rejections, and a snapshot that is written once per day and never overwritten.

### T5 — Alpaca news client (I-12)

`src/arcis/recorder/client.py`:

- `iter_news(symbols, start, end)` yields pages, following the pagination token found in T1 until exhausted, with `include_content=true` (needed for the hashes), `sort=asc`, and `limit` from `http.page_limit`.
- The universe is split into chunks of `http.symbols_per_request`, about 10 chunks for the S&P 500.
- Retries use exponential backoff with jitter on 429, 5xx, and timeouts, up to `http.max_retries`. When rate-limit headers show zero remaining, wait until the reset time.
- Typed errors: `AuthError` (401/403, never retried), `BadRequestError` (400), `RateLimitError` (retries exhausted), `UpstreamError` (5xx or timeouts exhausted).
- Each response's `Date` header is captured for the clock check (T8).
- A descriptive `User-Agent` is set. Headers and response bodies are never logged.

**Done when:** tests cover pagination, each error class, retry exhaustion, and rate-limit waits, with the sleep function injected so tests run instantly.

### T6 — Append-only store, manifests, and verify

`src/arcis/recorder/store.py`:

- Layout: `raw/news/alpaca/YYYY/MM/YYYY-MM-DD.jsonl`, partitioned by the **UTC date of `fetched_at`**.
- One line per newly seen article version:

  ```json
  {"schema": "news_obs.v2", "fetched_at": "<UTC RFC-3339 with microseconds>", "server_date": "<HTTP Date header>", "poll_id": "<uuid4>", "mode": "poll|sweep|override", "storage_mode": "fingerprint|full", "version_sha256": "<hex>", "text_sha256": {"headline": "<hex or null>", "summary": "<hex or null>", "content": "<hex or null>"}, "item": {"...": "see below"}}
  ```

- `text_sha256` holds the SHA-256 of each field's exact UTF-8 string, or null if absent.
- In fingerprint mode, `item` is the article as received **with `headline`, `summary`, and `content` removed**. In full mode, `item` is the article exactly as received.
- Each write appends the line and a newline, then flushes and calls `fsync`.
- **Sealing:** at the start of every run, each unsealed file for a UTC date before today gets `YYYY-MM-DD.manifest.json` (`lines`, the file's `sha256`, first and last `fetched_at`) and is set read-only. The writer refuses to touch a sealed date.
- `verify [--date D]` recomputes file hashes against manifests and validates every line against the schema, recomputing `version_sha256` only for full-mode records. Any mismatch exits non-zero.

**Done when:** tests prove append behavior, refusal on a sealed date, manifest correctness, that `verify` catches a single altered byte, and that fingerprint-mode lines carry no `headline`, `summary`, or `content` keys.

### T7 — Version index and rebuild

- `version_sha256` is the SHA-256 of the **complete** article's canonical JSON (sorted keys, compact separators, UTF-8), computed **before** any text is removed and **excluding the volatile fields found in T1**. The excluded fields are a named constant in code and are listed in the sprint report.
- A derived SQLite index at `index/news_versions.sqlite` (WAL mode) holds `versions(article_id INTEGER, version_sha256 TEXT, updated_at TEXT, first_fetched_at TEXT, file TEXT, PRIMARY KEY (article_id, version_sha256))`.
- A version is written to the store only if its key is not already indexed.
- Order of operations: append the line with `fsync`, then insert the index row. A crash between the two leaves a duplicate line with a later `fetched_at`, which is acceptable because the index always keeps the **earliest** `fetched_at`.
- `rebuild-index` recreates the index from stored lines alone and must produce identical rows.

**Done when:** tests cover a repeated article (one line), a changed article with the same `id` (two versions), a text-only change (a new version, even in fingerprint mode), the crash-between-writes case, and rebuild equivalence.

### T8 — `poll`, `sweep`, and `gaps` commands (I-10)

`python -m arcis.recorder poll` and `sweep` differ only in lookback. For recovery after a long outage, `sweep --lookback-hours N` overrides it and is logged with `mode: override`.

Each run:

1. Takes an **OS-level exclusive lock** on `locks/recorder.lock` (`msvcrt` on Windows, `fcntl` elsewhere), held for the process lifetime so it releases automatically on death. If held, log `skipped: another instance running` and exit 0 without a heartbeat.
2. Validates config, secrets, data root, and universe; logs the storage mode; writes the day's universe snapshot if missing.
3. Seals past-date files (T6).
4. Requests the window `[now − lookback, now]` for every symbol chunk.
5. **Clock check:** compares local UTC time with each response's `Date` header. Above `clock.warn_skew_seconds`, log a warning. Above `clock.max_skew_seconds`, abort before writing anything, because `fetched_at` is the evidence.
6. Writes new versions (T6, T7).
7. Appends one line to `logs/polls.jsonl`: `poll_id`, `mode`, `storage_mode`, start and end times, status, articles seen, new versions, pages, requests, rate-limit remaining, maximum clock skew, and the universe snapshot hash.
8. On success, pings `ARCIS_HEARTBEAT_URL`. On failure, pings `<url>/fail`, logs the typed error, and exits 1.

The only broad exception handler allowed is at the CLI entry point; it logs, sends the failure ping, and exits non-zero, with one `noqa: BLE001` and a justification comment.

**`gaps --since D`** reads `logs/polls.jsonl`, lists every interval longer than `gaps.max_gap_minutes` without a successful run of any mode, and exits non-zero if any exist.

**Done when:** an end-to-end test with mocked HTTP produces the expected files, index rows, poll-log line, and heartbeat call in both storage modes; failure-path and lock-contention tests pass; and the clock-skew abort is tested with an injected clock.

### T9 — Tests, coverage, and live smoke

- Every test from T3 to T8 runs offline against synthetic fixtures.
- Line coverage for `src/arcis/recorder/` is at least 90%.
- One live test, marked `live`, skipped unless `ARCIS_LIVE_TESTS=1` and both Alpaca keys are set: run `poll` in fingerprint mode into a temporary data root, then `verify`, then confirm no headline returned by the API appears anywhere in the stored files. Run it once before opening the PR, paste its poll-log line into the sprint report, and delete the temporary data root.

**Done when:** the offline suite is green in CI and the live result is recorded, or its absence is stated plainly.

### T10 — Runbook, documentation, and PR

- `docs/runbooks/recorder.md`:
  - Setting the environment variables on Windows (user scope).
  - Task Scheduler: `poll` every 10 minutes and `sweep` daily at a fixed early-morning local time, with "run whether user is logged on or not," "do not start a new instance," and "wake the computer to run this task." Include a `Register-ScheduledTask` snippet for each.
  - Healthchecks.io: one check, 10-minute period, 20-minute grace.
  - Daily operator check: `gaps --since <yesterday>` and `verify`.
  - Recovery: `sweep` covers up to 72 hours; longer outages use `sweep --lookback-hours N`, and late capture shows honestly in `fetched_at`.
  - **Storage mode:** why fingerprint mode is the default, that switching to full mode requires Alpaca's written confirmation recorded in SCOPE.md §9 first, and that fingerprint-mode versions can only be recovered by re-querying the archive and matching `version_sha256`.
  - Where the data lives and why it stays outside the repo and outside sync folders.
- Update the README documentation map with the runbook, and the Status section with what now exists.
- Add the CHANGELOG entry.
- Update SCOPE.md D-004 with the preflight result.
- Append the sprint report below: what was built, deviations and why, T1 findings, the volatile-field list, and open issues.

**Done when:** a new reader could install, configure, schedule, and verify the recorder from the runbook alone.

---

## Acceptance criteria

1. T1 findings are recorded, and no response body was persisted. If access was refused, the sprint ends after T1 and nothing else merges.
2. The repository layout matches the target, with no leftover duplicates at the root.
3. README.md and CLAUDE.md exist as specified, and the documentation map lists every document in the repo.
4. CI is green: ruff, mypy, pytest at 90% coverage on `recorder`, ledger, size, and hygiene checks.
5. No `src/` file exceeds 400 lines and no function exceeds 60 lines.
6. Exactly one broad exception handler exists, at the CLI entry point, with a justification.
7. In fingerprint mode, no stored file contains article headline, summary, or body text, proved by tests and the live smoke check.
8. A universe snapshot exists for every day the recorder ran.
9. The live smoke result is recorded, or its absence is stated.
10. Nothing from **Out** appears in the diff, and `recorder` is the only subpackage under `src/arcis/`.

## After merge (Ryan)

1. Set the three environment variables on the host.
2. Register both scheduled tasks from the runbook.
3. Create the Healthchecks.io check.
4. GitHub settings: require the CI check before merging on `main`, confirm secret-scanning push protection is on, and turn off wiki and projects if unused.
5. After 7 days with `gaps` clean and `verify` passing, Step 1 is done (SCOPE.md §5).

## Sprint report

_(Claude Code appends here.)_

---

## Ralph Loop log (spec review before hand-off)

**Pass 1 — draft.** Scope, API facts from Alpaca's docs, and ten tasks with a preflight gate.

**Pass 2 — gap review.** Found and fixed:

1. Re-reading a 24-hour window with full content every 10 minutes would download on the order of 100 MB a day. Split into a 2-hour `poll` plus a daily 72-hour `sweep`.
2. A field that changes on every request would make every poll look like a new version. T1 now identifies volatile fields, and T7 excludes them from the hash.
3. `fetched_at` is only as trustworthy as the host clock. Added the server `Date` header check with an abort threshold.
4. Test fixtures would have committed real Benzinga content. Fixtures are now synthetic.
5. File-based locks go stale after a crash. Replaced with an OS-level lock that releases when the process dies.
6. The ledger check would have allowed live-lane packages to appear early. SCOPE.md now has an Active column, and CI enforces it.
7. A crash between the append and the index insert was undefined. Defined as a tolerated duplicate, with the earliest `fetched_at` winning, plus a rebuild-equivalence test.
8. There was no path for outages longer than 72 hours. Added `sweep --lookback-hours` as a logged override.

**Pass 3 — polish.** Added a "done when" to every task, moved secrets to environment-only, capped dependencies, made the 401/403 path an explicit stop, and required tests to ship with each task.

**Pass 4 — research-log revision (R08).**

1. Public terms do not clearly allow retaining article text. Added fingerprint mode as the default, with per-field hashes, and made full text a rights-gated switch.
2. The version hash must still detect text-only revisions, so it is computed on the complete article before text is removed, with a test for that case.
3. T1 would have saved raw responses to disk. It now inspects them in memory only.
4. The research universe was undecided and forward capture cannot be added later, so the capture universe became the S&P 500 with S&P 100 members flagged.
5. `verify` cannot recompute a version hash without text, so it validates schema and file hashes in fingerprint mode.

**Pass 5 — repository and documentation review.**

1. The sprint built code into an empty repository with no structure, no README, and no rules for future agent sessions. Added T2 for the scaffold, the documentation map, CLAUDE.md, the CHANGELOG, and the PR template, and moved tooling and CI into T3.
2. Four documents sat at the repository root with no home. T2 now moves them into the layout in one place.
3. The repository is public, and CI checked code quality but not what was being committed. Added `tools/check_hygiene.py` for data files, oversized files, credential-shaped strings, and sprint-file naming, with a justified pragma for exceptions.
4. "Run the checks" meant something different locally and in CI. Added `tools/checks.py` as the single entry point that CI also runs.
5. Documentation updates were implicit and would have been skipped under time pressure. The README map, CHANGELOG, and sprint report are now explicit in T10, in the PR template, and in CLAUDE.md.
6. Configuration, the data-root guard, and the universe were three separate tasks, which pushed the count over ten once repository work arrived. They are one task now, since they all run at startup and share their tests.
7. Repository settings that a sprint cannot change, such as branch protection and push protection, were invisible. They are now explicit operator steps after merge.
