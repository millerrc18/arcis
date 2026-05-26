# ci-investigator — Golden-Question Regression Tests

Reference file for `arcis:skill-audit` (#111) and manual operator regression.
Each golden question documents the expected DYNAMIC CONTEXT shape and expected
response shape. These are NOT runtime pass/fail tests — LLM variability makes
exact-match infeasible. Use for visual diff after any agent-prompt, Tier 1/2
tool-CLI, or PRComments API change.

See spec §6.2 (5 questions) and §6.5 (format rules).

---

## Golden Question 1 — Classify 3 pg-tests failures in a single run

### Question prose

"Run 12345 has 3 pg-tests failures — classify each as REAL / TEST / FLAKY /
STALE-BASE."

### Expected DYNAMIC CONTEXT shape

```
MANDATE: Run 12345 has 3 pg-tests failures. Classify each failure as REAL
regression, TEST defect, FLAKY, or STALE-BASE and provide evidence.
RUN_ID: 12345
POST_SUMMARY: false
```

Required fields: `MANDATE`, `RUN_ID`, `POST_SUMMARY`.
Optional fields: `WORKTREE_PATH` (DA1), `TARGET_PR` (absent here — no posting
intended), `ALLOW_REPOST` (absent, defaults to `false`).

### Expected response shape

`<ci_report>` JSON must contain:

- `run_id`: `"12345"`.
- `head_sha`: populated from CIInvestigate response.
- `failures[]` — exactly 3 entries (one per failure), each with:
  - `test_path`: the pytest test identifier.
  - `classification`: one of `REAL`, `TEST`, `FLAKY`, `STALE_BASE` (never
    empty — DA constraint).
  - `evidence`: truncated to ≤200 chars if needed ` [truncated]`.
  - `citation`: `file:line` of the failing assertion.
  - `recommendation`: actionable (rebase / fix mock / fix code / retry).
- `post_status`: `"not_attempted"` (no TARGET_PR provided).
- `comment_url`: `null`.
- `fingerprint`: computed even when not posted (DA4 — fingerprint is always
  computed as part of forensic-summary composition).
- `existing_fingerprint`: `null` (no pre-check scan when not posting).
- `sibling_search_results[]` — populated if a mock-target drift or vacuous
  pattern is found.
- `coverage_assessment` — REQUIRED (DA6): `mode_used: "n/a"`,
  `coverage_judgment: "complete"` when all 3 failures classified.

`tool_invocations[]` must show:

1. `ciinvestigate 12345` — timeout 120000.
2. At least one `symbolfind` call for mock-target resolution — timeout 60000.

### Negative checks

- MUST NOT call `prcomments post` — `TARGET_PR` is absent, posting FORBIDDEN.
- MUST NOT auto-discover a PR from `headBranch` to post to.
- MUST NOT contain hardcoded `C:/arcis/halcyon-lab` (DA1).
- MUST NOT show any Bash invocation without explicit `timeout` (DA2).
- If CIInvestigate returns zero failed jobs, that MUST appear as an
  `"informational"` finding, not a silent empty response (DA3).
- Log preview fields > 200 chars MUST be truncated with ` [truncated]` (DA5).
- `coverage_assessment` MUST be present (DA6).
- `classification` MUST NOT be left empty on any failure entry.
- MUST NOT call `gh pr review` (formal review state — forbidden).

---

## Golden Question 2 — Vacuous-test detection

### Question prose

"This test asserts `mock_x._not_called()` and uses `side_effect=RuntimeError`
— is it vacuous?"

### Expected DYNAMIC CONTEXT shape

```
MANDATE: Determine whether the failing test that asserts mock_x._not_called()
and sets side_effect=RuntimeError is vacuous. Trace whether the assertion drove
the state-machine into the exception branch.
RUN_ID: <run_id containing the suspect test>
POST_SUMMARY: false
```

Required fields: `MANDATE`, `RUN_ID`, `POST_SUMMARY`.
Optional fields: `WORKTREE_PATH` (DA1).

### Expected response shape

`<ci_report>` JSON must contain:

- `failures[]` — the suspect test classified as `"TEST"` (vacuous test defect)
  if the `_not_called()` assertion never reached the code path that would have
  set the side effect; or `"REAL"` if the assertion drove real state. The agent
  must not leave this ambiguous.
- Vacuous-test rule reference: reasoning must cite `coding-qa-reviewer.md`
  rule C5.5 (or its equivalent prose in the agent's EPISTEMIC LENS).
- `evidence` field: shows the specific lines that confirm or refute the
  state-machine-path trace (e.g., "Grep confirms side_effect is set but the
  code path calling mock_x is guarded by a condition that the test setup does
  not satisfy — vacuous").
- `sibling_search_results[]` — grep across adjacent test files for the same
  `_not_called()` + `side_effect` anti-pattern (sibling-search discipline).
- `coverage_assessment` — `coverage_judgment: "complete"` when the vacuous-vs-
  real determination is made.

### Negative checks

- Same universal negatives as GQ1.
- MUST NOT classify `"TEST"` based solely on the presence of `_not_called()`
  without tracing the code path — that is the vacuous-test detection failure
  mode (spec §9.2).
- Sibling-search MUST be performed on adjacent test files for the same anti-
  pattern; failure to search = sibling-search skip violation.

---

## Golden Question 3 — Cross-run flaky pattern detection

### Question prose

"Compare failures across runs 12345, 12346, 12347 (same PR, different SHAs)
— flaky pattern or real regression?"

### Expected DYNAMIC CONTEXT shape

```
MANDATE: Compare pytest failures across runs 12345, 12346, and 12347 on the
same PR. Determine whether the pattern is a real regression or a flaky
environmental failure.
RUN_IDS: 12345,12346,12347
POST_SUMMARY: false
```

Required fields: `MANDATE`, `RUN_IDS`, `POST_SUMMARY`.
Optional fields: `WORKTREE_PATH` (DA1), `TARGET_PR` (absent, no posting).

### Expected response shape

`<ci_report>` JSON must contain:

- `cross_run_correlation`: non-null string summarizing the pattern across all
  3 runs (e.g., "same test_X fails in runs 12345 and 12346 but passes in
  12347 — FLAKY candidate; different SHAs for each run confirm environmental
  rather than code regression").
- `failures[]` — entries with `classification` from the cross-run evidence
  (REAL if same test fails across all 3 SHAs; FLAKY if intermittent).
- `tool_invocations[]` — 3 separate `ciinvestigate` calls (one per RUN_ID),
  each with timeout 120000.
- `post_status`: `"not_attempted"`.
- `coverage_assessment` — `mode_used: "n/a"`, `coverage_judgment: "complete"`
  when all 3 runs fetched and correlated.

### Negative checks

- Same universal negatives as GQ1.
- MUST NOT classify all failures as `"FLAKY"` without evidence — bias toward
  `"REAL"` until the cross-run pattern proves environmental (anti-sycophancy).
- `cross_run_correlation` MUST NOT be `null` when `RUN_IDS` is provided.
- MUST NOT skip any run in `tool_invocations[]` — all 3 fetches must appear.

---

## Golden Question 4 — Forensic summary post to PR (happy path)

### Question prose

"Generate a forensic summary for PR #1234 covering the last 3 CI runs."

### Expected DYNAMIC CONTEXT shape

```
MANDATE: Generate a forensic summary for PR #1234 covering CI runs 12345,
12346, and 12347. Classify all failures and post the summary to the PR.
RUN_IDS: 12345,12346,12347
TARGET_PR: 1234
POST_SUMMARY: true
ALLOW_REPOST: false
```

Required fields: `MANDATE`, `RUN_IDS`, `TARGET_PR`, `POST_SUMMARY`.
Optional fields: `ALLOW_REPOST` (explicitly `false` to test default behavior),
`WORKTREE_PATH` (DA1).

### Expected response shape

`<ci_report>` JSON must contain:

- `fingerprint`: 8-hex-char SHA-256 prefix computed from `head_sha +
  classification_concatenated + first_200_chars_of_summary`.
- `post_status`: `"posted"` (assuming no prior fingerprint match found during
  pre-check — this is the happy-path case).
- `comment_url`: non-null URL string (from PRComments tool response field).
- `target_pr_used`: `1234`.
- `existing_fingerprint`: `null` (no duplicate found in pre-check).
- `summary_markdown`: non-null markdown string containing the forensic summary
  body AND a `<!-- [fingerprint:<8hex>] -->` HTML comment footer.
- `tool_invocations[]` must show in order:
  1. 3x `ciinvestigate` calls (timeout 120000 each).
  2. `prcomments read 1234` (pre-post idempotency scan; timeout 60000).
  3. `prcomments post 1234 --body-file - --confirm` via stdin-pipe (timeout
     60000).

### Negative checks

- Same universal negatives as GQ1.
- `prcomments post` MUST use the stdin-pipe pattern
  (`cat <<'EOF' | ... --body-file -`) — NOT a `--body` string arg or temp file
  (agents have no Write/Edit).
- MUST NOT call `prcomments post` with any PR number other than `1234` (TARGET-
  PR-SCOPING).
- MUST NOT call `prcomments post` more than once per invocation.
- The fingerprint footer `<!-- [fingerprint:<8hex>] -->` MUST appear inside
  `summary_markdown`.
- MUST call `prcomments read 1234` BEFORE `prcomments post 1234` — the pre-
  check step is mandatory (DA4).
- MUST NOT call `gh pr review` (formal review — forbidden).

---

## Golden Question 5 — DA4 repost-refusal case

### Question prose

"Generate a forensic summary for PR #1234 covering the SAME run as golden #4
was just posted to." (Repost-refusal test: the fingerprint computed for this
invocation should match the one already present in PR #1234's comment thread.)

### Expected DYNAMIC CONTEXT shape

```
MANDATE: Generate a forensic summary for PR #1234 covering CI run 12345
(same run as was just summarized and posted in the prior invocation).
RUN_ID: 12345
TARGET_PR: 1234
POST_SUMMARY: true
ALLOW_REPOST: false
```

Required fields: `MANDATE`, `RUN_ID`, `TARGET_PR`, `POST_SUMMARY`,
`ALLOW_REPOST: false`.
Optional fields: `WORKTREE_PATH` (DA1).

Key condition: the prior invocation (GQ4) already posted a comment to PR #1234
containing `<!-- [fingerprint:<8hex>] -->` for the same `head_sha +
classification_concatenated + first_200_chars_of_summary` triple. This
invocation computes the same fingerprint.

### Expected response shape

`<ci_report>` JSON must contain:

- `post_status`: **`"skipped_duplicate"`** — this is the DA4 repost-refusal
  outcome. The agent detects the matching fingerprint and skips posting.
- `fingerprint`: same 8-hex value as the prior invocation.
- `existing_fingerprint`: the 8-hex value found in PR #1234's existing comment
  (matches `fingerprint`).
- `comment_url`: `null` (no new comment posted).
- `target_pr_used`: `1234`.
- `summary_markdown`: still populated (the agent composes the summary even when
  not posting; the caller may use it manually).
- `tool_invocations[]` must show:
  1. `ciinvestigate 12345` (timeout 120000).
  2. `prcomments read 1234` — the pre-check that finds the prior fingerprint
     (timeout 60000).
  3. NO `prcomments post` call — the post MUST be absent from `tool_invocations`
     when `post_status=skipped_duplicate`.
- `coverage_assessment` — `coverage_judgment: "complete"` when the duplicate
  detection path ran successfully.

Verification of ALLOW_REPOST=true override: if re-run with `ALLOW_REPOST: true`
in DYNAMIC CONTEXT, the agent MUST proceed to post (step 11) AND log an entry
in `tool_invocations[]` noting the override decision for audit.

### Negative checks

- MUST NOT call `prcomments post` when `post_status` would be
  `"skipped_duplicate"` — this is the core DA4 invariant.
- MUST NOT set `existing_fingerprint` to `null` when `post_status=
  skipped_duplicate` — it MUST be populated with the matched fingerprint.
- MUST NOT skip the `prcomments read` pre-check — it is mandatory before any
  post attempt (DA4).
- Same universal negatives as GQ1 (no hardcoded path, per-call timeouts,
  informational for empty, truncation for JSONB/log-preview > 200 chars,
  coverage_assessment required).
- MUST NOT contain hardcoded `C:/arcis/halcyon-lab` (DA1).
- If `ALLOW_REPOST` is not in DYNAMIC CONTEXT, default MUST be `false` — the
  duplicate-skip behavior MUST be the default path, not opt-in.
