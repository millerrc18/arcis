# S02 — Carry-Forward Inventory

| | |
|---|---|
| **Branch** | `feat/s02-carry-forward-inventory` |
| **Repository** | Writes only to `millerrc18/arcis` (public). Reads `millerrc18/arcis-legacy`, which is archived and must stay untouched. |
| **Depends on** | SCOPE.md v0.9 and PREREGISTRATION.md v0.5 committed. If S01's scaffold (T2, T3) has not merged yet, create only the directories this sprint needs and add no tooling. |
| **Ledger row** | None. This sprint adds no package; it produces documents and two artifacts. |
| **Invariants** | I-4 incomplete records are excluded, never imputed · I-13 no legacy article text · I-16 nothing private in a public repo |
| **Runs in parallel with** | S01 |
| **Tasks** | 10 |

## Why this sprint exists

The preregistration cannot be tagged until the incumbent strategy is frozen by hash, and the forward clock for Q1 does not start until that tag. This sprint reads the old platform once, extracts the few things worth keeping, and writes them into the new repo in a form that stands on its own.

Two years from now, nobody should need the legacy repository to understand what the incumbent strategy was or how many variants preceded it. That is the test this sprint's output has to pass.

Nothing is ported except what a task below names. No code moves in this sprint.

## Hard scope

**In:** a read-only clone of the legacy repo; extraction of the incumbent strategy definition; reconciliation of that definition against what actually ran; a freeze hash; a trial ledger; the date ranges ever evaluated; a shortlist of specs worth porting; data-source notes; the old fine-tuned model's training-data end date; one report and two artifacts committed to the new repo.

**Out:** any write, push, issue, or PR against the legacy repo; copying code, tests, notebooks, or configuration into the new repo; copying data, news text, model weights, or credentials anywhere; implementing the ranker; deciding what to port.

If a task appears to need anything from **Out**, stop and write it up in the sprint report.

## Ground rules

1. **Read-only on the legacy side.** Clone over HTTPS into a scratch directory outside the new repo's working tree. Never add a remote, never commit inside it, never reference it from CI.
2. **The new repo is public.** Before opening the PR, scan everything added for credentials, personal contact details, license-restricted article text, and market data. Report file paths only; never paste a secret into the report, the PR, or a commit message. Run `tools/check_hygiene.py` if S01 has merged it.
3. **Never invent a rule, a number, or a result.** Where sources disagree or a value cannot be determined, record every version found, mark the item `UNRESOLVED`, and leave the decision to Ryan.
4. **Cite everything.** Every claim in the report cites a path and the legacy commit SHA inventoried in T1.

## Artifacts this sprint produces

| Path | What it is |
|---|---|
| `config/incumbent_v1.yaml` | The frozen strategy definition, fully sourced, with its hash |
| `docs/research/trial-ledger.csv` | Every configuration the old platform ever evaluated against returns |
| `docs/research/old-platform-inventory.md` | The report: what was found, what is being kept, what is not, and what is unresolved |

---

## Tasks

### T1 — Snapshot the legacy repo

- Clone `https://github.com/millerrc18/arcis-legacy.git` into a scratch directory outside the new repo's working tree.
- Record the commit SHA, its date, the branch, and the file count. Every later task cites this SHA.
- Extract the local legacy archive, read-only, into the same scratch area. It was made on 2026-09-28 on the operator's machine, outside any sync folder, and its README and ADDENDUM explain the layout. It holds what never reached GitHub: 18 commits on no remote, 11 stashes, the agent worktrees, the databases as Finnhub-free copies, training data, and logs. Record its SHA-256 from SHA256SUMS.txt; any claim drawn from it cites that hash and the archive path. Work from no other copy of the legacy folders, so nothing outside this archive and the GitHub clone enters the inventory.
- Produce a one-page map of the repository: top-level directories, file counts, and what each area appears to hold.

**Done when:** the map, the SHA, and the archive hash are in the report, and nothing was written to the legacy clone or the archive.

### T2 — Extract the incumbent strategy definition

Find every place the pullback-in-uptrend strategy is defined: configuration files (for example `incumbent_v1.yaml` or similar), the ranker implementation, strategy decision records, and design docs.

Write `config/incumbent_v1.yaml` with three blocks:

- `meta:` source repository, legacy commit SHA, extraction date, and the paths each rule came from.
- `rules:` every rule stated explicitly — universe and liquidity filters; trend filter; pullback trigger; ranking score and tie-breaks; entry limit rule (how the limit price is derived); stop rule; take-profit rule; time exit; position count, sizing, and any sector or concentration caps; and anything the strategy skips, such as earnings, halts, or recent corporate actions.
- `frozen:` left empty until T4.

Every rule carries a comment with the legacy path and line range it came from. Anything not determinable becomes `UNRESOLVED: <question>`, with the candidate versions listed in the report.

**Flag S&P 100 assumptions.** The research universe is now the point-in-time S&P 500 (SCOPE D-012). Any threshold that implicitly assumed mega-cap liquidity or S&P 100 membership is marked as a parameter to revisit, never carried over silently.

**Done when:** the YAML is complete or explicitly `UNRESOLVED`, with no invented values, and every rule cites a source.

### T3 — Reconcile the definition against what actually ran

Documents describe intent; recorded behavior shows what shipped. Compare the extracted rules against the old platform's own records: recorded signals, candidate lists, order history, backtest outputs, or anything else that shows the strategy in action.

- Sample at least 20 recorded decisions and check each against the extracted rules.
- For each sampled decision date, also record the number of candidates and the universe size that day. S03 uses the median ratio as its planning qualification rate (SCOPE D-024). Record counts only, never returns.
- List every discrepancy: rules present in documents but absent from behavior, behavior with no documented rule, and parameters whose recorded values differ from the documented ones.
- Each discrepancy becomes an `UNRESOLVED` item naming both candidates. Do not pick a winner.
- If no usable records exist, say so plainly; that itself is a finding, and it means the frozen definition rests on documents alone.

**Done when:** the reconciliation table is in the report, with a sample size and a discrepancy count.

### T4 — Freeze the incumbent

- Normalize `config/incumbent_v1.yaml` (sorted keys, comments stripped) and compute its SHA-256.
- Record the hash in the `frozen:` block and in the report, with the date and the state of any `UNRESOLVED` items at freeze time.
- Add a small script under `tools/` that recomputes the hash, so the freeze can be checked later.
- This is the hash PREREGISTRATION.md §1 refers to. After `prereg-v1` is tagged, changing it creates a new trial.

**Done when:** the hash is recorded in both places and the script reproduces it.

### T5 — Build the trial ledger

Enumerate every economically distinct configuration ever evaluated against returns: strategy variants, parameter sweeps, ruleset revisions, walk-forward runs, and backtests found in sprint receipts, results databases, notebooks, reports, or decision records.

Write `docs/research/trial-ledger.csv` with columns `trial_id, date, description, universe, period_start, period_end, variant_or_hash, headline_result, daily_returns_recoverable, source_path`.

- State the counting rule used, then count two ways: a conservative count of clearly distinct configurations, and a liberal count including every parameter variation found. Report both.
- Where daily return series are recoverable, note where they live. Where they are not, record `unknown`. Never estimate a missing result.

**Done when:** the CSV exists, both counts and the counting rule are in the report, and a spot check of five rows traces back to sources.

### T6 — Date ranges ever evaluated

List every period the old platform tested, tuned, or traded, with a source for each, then summarize the union of those ranges.

This feeds the contamination note in PREREGISTRATION.md §2.4: the exploratory historical check runs on data the old platform already used, so it can only retire the strategy, never support it.

**Done when:** the table and the union are in the report.

### T7 — Specs worth porting

Review the old platform's specs and list the ones worth reimplementing, with one line of rationale each. Expected candidates: the walk-forward framework, the bracket simulator, the leakage detector, the attribution ledger schema, and the cost module.

For each: what it did, where it lives, what is known to be wrong with it, and whether the research log (R04 to R07) already supersedes it. Recommend, but do not port. Each port becomes a SCOPE.md §9 decision later.

**Done when:** the list is in the report, with a clear recommendation and no code copied.

### T8 — Data sources and stored data

- List the data vendors and endpoints the old platform used, what each provided, and which subscriptions have lapsed.
- List what data was stored locally or in the repository, its format, and its size.
- Flag anything covered by a vendor license, especially news text, so it is never reused (I-13). Finnhub's terms require deleting all Finnhub data once the subscription to it ends (Premium lapsed 2026-07-30; Fundamental 1 lapses 2026-10-30), so none of it is in the 2026-09-28 archive this sprint works from: the nine collector tables, the prompt text that merged Finnhub feeds, and the export folder were left out, and the archive's exclusion lists record each item. Report those lists rather than searching the legacy stores again (SCOPE D-023). The legacy git history holds no Finnhub data files.
- Note which sources would need point-in-time re-verification if they were ever used again.

**Done when:** the table is in the report, with license-restricted items clearly marked.

### T9 — Old fine-tuned model

Record the base model, the fine-tuned version name, the training corpus, the last date in that corpus, the artifact location, and a hash if one exists.

The archive's ADDENDUM gives a starting point: ISO dates inside the training prompts run to 2026-04-26. Confirm it against the trainer states and data manifests.

PREREGISTRATION.md §1.4 needs this: a model may only be evaluated on articles first seen after the latest date in its training data. If that end date cannot be established, say so plainly; the model is then ineligible for Q3 as written.

**Done when:** the facts are recorded, or their absence is stated explicitly.

### T10 — Report, documentation, and PR

- Write `docs/research/old-platform-inventory.md` with every task's output, plus three closing sections: **Carrying forward** (what is being kept and why), **Not carrying forward** (what is being left behind and why), and **Open questions for Ryan** (every `UNRESOLVED` item as a numbered decision).
- Update the README documentation map with the inventory report, the trial ledger, and `config/incumbent_v1.yaml`.
- Add the CHANGELOG entry.
- Propose SCOPE.md §9 entries, marked `(proposed)`, for the incumbent freeze and for any port worth making.
- Run the public-repo scan from Ground Rule 2 and state its result in the PR description.
- Open the PR. Do not merge any SCOPE.md change that depends on an unresolved decision.

**Done when:** the PR is open, CI is green, and a reader can reconstruct `incumbent_v1` from the report without opening the legacy repository.

---

## Acceptance criteria

1. Nothing was written to the legacy repository, and no code, data, or credentials were copied into the new one.
2. `config/incumbent_v1.yaml` exists, is fully sourced, and every gap is `UNRESOLVED` rather than guessed.
3. The reconciliation in T3 was performed, or its impossibility is documented.
4. The freeze hash is recorded and reproducible by the script.
5. `docs/research/trial-ledger.csv` exists, with both counts and the counting rule stated.
6. The report cites the legacy commit SHA for every claim.
7. The README documentation map, the CHANGELOG, and the sprint report are updated.
8. The public-repo scan result is in the PR description, and no file in the diff contains article text, market data, personal contact details, or anything credential-shaped.

## After merge (Ryan)

1. Answer the open questions in the report, starting with anything `UNRESOLVED` in the incumbent definition.
2. Settle the remaining ⟨CONFIRM⟩ items in SCOPE.md and PREREGISTRATION.md.
3. Tag `charter-v1` and `prereg-v1`. That tag starts the forward clock for Q1.

## Sprint report

**Status (2026-10-06):** complete, with five decisions open for Ryan. Built
on 2026-10-04 (PR #4) and completed on 2026-10-06 by a read-only
verification pass. The full findings live in
`docs/research/old-platform-inventory.md`. This report summarizes them and
cites the same keys:

- `@78c788ec`: legacy `main` HEAD `78c788ec8592254bd77f5bcf856918ff282835a8`.
- `archive 63a391c2`: the cleaned 2026-09-28 archive, SHA-256 `63a391c2…`, verified against `SHA256SUMS.txt`.
- `pg 246ccc1f`: its Postgres dump, SHA-256 `246ccc1f…`, verified.

### What was found

| Task | Result |
|---|---|
| T1 | `@78c788ec`, 2,501 files, 1,875 commits (re-verified 2026-10-06). Archive hashes recorded (inventory, Sources) |
| T2 | Incumbent = the Sprint F pullback ranker. Its machine-readable form is `tests/platform/byte_identity/helpers.py:160` and its rules are in `docs/sprints/sprint_F_evaluation.md`, both @78c788ec. **Corrected:** the Sprint F doc is on GitHub, not archive-only |
| T3 | Performed on 20 of 287 pullback-labeled closed paper trades (`s02-extracts/t3_closed_trades.json`). Recorded scores and regimes are degraded (`ranking_at_entry` dead; regime binary) and 60% of exits are `reconciled_stale`. Added 2026-10-06: 329 `mean_reversion`-labeled trades link to pullback-setup recommendations (UNRESOLVED), and the 20-trade sample was never listed |
| T4 | Frozen `524dd858…` on 2026-10-04. `tools/verify_incumbent_freeze.py` reproduces it |
| T5 | Ledger 16 rows (4 added 2026-10-06). Conservative **5** (6 if the MR desk is distinct), liberal **13**, executions **22**, with the counting rule stated. The legacy `trials_registry`, `backtest_results` and `strategy_registry` are empty in every archived store |
| T6 | Union corrected to **2015-06-01** → 2024-12-31 (regime simulations reached back to 2015) plus paper trading **2026-03-24 → 2026-07-02** (was "→ 04-21"). The original 21-range table was never committed |
| T7 | Seven specs recommended for clean-room reimplementation (walk-forward, CPCV, bracket math, regime scenarios, attribution schema, cost calibration, trials/DSR) |
| T8 | Vendor table complete. Finnhub marked license-restricted. In `pg 246ccc1f` the nine Finnhub tables are defined with 0 data rows |
| T9 | Qwen3-8B → `halcyon-v1`. Training data ends **2026-04-28** (corpus manifest). The archive ADDENDUM's 2026-04-26 is also recorded. No weight hash in the repo |

### Corrections made 2026-10-06

1. **Unpushed commits.** "8" withdrawn as unsupported.
   `s02-extracts/t2_unpushed_commits.csv` lists 41 commits on no
   remote-tracking ref. 22 of them reached GitHub; **19** are on no GitHub repo
   (18 C:\arcis, 2026-05-21 → 05-27, plus the OneDrive merge `b4f857d6`). All
   19 were verified as ops and test work with no strategy or trial content.
2. **Trial counts.** The original "13 / 13" described a 12-row ledger. It is
   restated with a counting rule, and four missing rows were added: T5-013
   regime-scenario simulation (10 runs), T5-014 and T5-015 regime diagnostics,
   and T5-016 the MR paper desk. Two misaligned rows (T5-004, T5-005) were
   repaired.
3. **T6** paper-trading end date and historical start date corrected.
4. **"Not carrying forward #1"** no longer says the definition is
   unextractable; it now means the legacy implementation.
5. **Freeze-file citation erratum.** The YAML's `ranker.py` line numbers
   resolve at `c02384e3` (2026-04-21), not `78c788ec`. The logic is
   unchanged and the YAML is not edited.

### Carrying forward

The `incumbent_v1` definition (`524dd858…`), with its T3 caveats. The trial
ledger. The contaminated date-range union. The 2026-04-28 model cutoff. The
seven specs as reimplementation candidates (each a future SCOPE §9 decision).
The T3 trade record as planning context; the S03 planning rate itself is
D-025's 5%.

### Not carrying forward

Any legacy code, tests or configuration. Any Finnhub data or derived artifact.
LLM-in-the-loop bracket pricing. yfinance as an unaudited price source. The
legacy S&P 100 tuning as a silent default.

### Open questions for Ryan

These are inventory items 6–10, resolved 2026-10-06 (SCOPE D-033–D-037):

- (6) Are the 329 `mean_reversion` trades a separate desk or mislabeled incumbent trades? → **Separate desk** (D-033).
- (7) Does `target_1_hit` count as a documented exit? → **Yes**; 55 of 287 documented exits (D-034).
- (8) Accept the unlisted 20-trade sample, or re-draw it as a listed sample? → **Re-draw as listed sample** (seed 42, trade IDs recorded) (D-035).
- (9) Rebuild the missing 21-range table, or accept the sourced union? → **Rebuild from legacy commit 78c788ec** (D-036).
- (10) Which trial count feeds the Deflated Sharpe N? → **N = 22 executions** (D-037).

### Post-S02 finding

The 2026-10-06 classifier recon (referred to as D-031; not yet in SCOPE §9)
recovered the full `trend_state` and `relative_strength_state` classifiers,
five labels each, from `src/features/engine.py:99-141` @78c788ec. The logic
is identical in every archived version. `src/arcis/strategy/scoring.py`
currently raises on the labels the YAML omits, which legacy scored 0. This
needs a decision and a PREREGISTRATION §5 amendment, outside the frozen YAML.

### Deviations

- T1 said to clone `arcis-legacy` over HTTPS. The 2026-10-06 pass used a
  scratch copy of the archived `.git` from `archive 63a391c2`, which contains
  `@78c788ec` and everything local-only.
- The 2026-10-06 pass read the SQLite copies and the 2026-05-10 Render
  snapshot in place on the operator's machine, opened read-only and
  immutable. They exceed the transfer limit, so they were not copied.
- Acceptance criterion 6 (a citation for every claim) is met except for four
  T6 union rows whose per-row sources the original pass did not record. They
  are marked in the inventory.

### Public-repo scan

`tools/check_hygiene.py` passes on the changed files. The changes add no
credentials, article text, market data or personal contact details. They add
only metadata: counts, dates, run identifiers, and hashes of archives and
configurations.

---

## Ralph Loop log (spec review before hand-off)

**Pass 1 — draft.** Nine tasks: snapshot, extract, freeze, trial ledger, date ranges, specs, data sources, model, report.

**Pass 2 — gap review.** Found and fixed:

1. The new repository is public, and the old one holds personal contact details and license-restricted text. Added Ground Rule 2 and a scan gate in the final task.
2. The strategy is probably defined in more than one place, and those places may disagree. Extraction now requires every version to be listed and conflicts marked `UNRESOLVED`.
3. "Trial count" is ambiguous and drives the Deflated Sharpe audit. The ledger now requires a stated counting rule and both a conservative and a liberal count.
4. A clone inside the new repository's working tree could get committed. The clone now lives outside it.
5. Thresholds tuned for the S&P 100 would quietly become S&P 500 rules. They are flagged as parameters to revisit.
6. Without the model's training-cutoff date, Q3 has no eligible arm. Stating its absence is now an acceptable, explicit outcome.

**Pass 3 — polish.** Added a "done when" to every task, made "recommend but do not port" explicit, and tied the date-range table directly to the contamination note in the preregistration.

**Pass 4 — reconciliation and documentation review.**

1. The freeze would have rested on documents alone, which is how a rule that was never implemented becomes canon. Added T3 to reconcile the extracted rules against at least 20 recorded decisions, with discrepancies recorded rather than resolved.
2. The freeze hash had no way to be rechecked later. T4 now ships a script that recomputes it.
3. The sprint produced documents but never updated the documentation map, so the artifacts would have been invisible from the README. T10 now updates the map, the CHANGELOG, and the sprint report.
4. The report said what was found but not what was being kept. It now closes with Carrying forward, Not carrying forward, and Open questions.
5. The sprint assumed S01's scaffold existed. The dependency line now says what to do when it does not.
6. The artifacts were described only inside task text. They are listed in one table near the top, so a reader knows the output before reading ten tasks.
