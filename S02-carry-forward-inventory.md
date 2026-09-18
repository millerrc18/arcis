# S02 — Carry-Forward Inventory

| | |
|---|---|
| **Branch** | `feat/s02-carry-forward-inventory` |
| **Repository** | Writes only to `millerrc18/arcis` (public). Reads `millerrc18/arcis-legacy`, which is archived and must stay untouched. |
| **Depends on** | SCOPE.md v0.7 and PREREGISTRATION.md v0.4 committed. If S01's scaffold (T2, T3) has not merged yet, create only the directories this sprint needs and add no tooling. |
| **Ledger row** | None. This sprint adds no package; it produces documents and two artifacts. |
| **Invariants** | I-4 incomplete records are excluded, never imputed · I-13 no article text · I-16 nothing private in a public repo |
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
- Produce a one-page map of the repository: top-level directories, file counts, and what each area appears to hold.

**Done when:** the map and the SHA are in the report, and nothing was written to the legacy clone.

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
- Flag anything covered by a vendor license, especially news text, so it is never reused (I-13).
- Note which sources would need point-in-time re-verification if they were ever used again.

**Done when:** the table is in the report, with license-restricted items clearly marked.

### T9 — Old fine-tuned model

Record the base model, the fine-tuned version name, the training corpus, the last date in that corpus, the artifact location, and a hash if one exists.

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

_(Claude Code appends here.)_

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
