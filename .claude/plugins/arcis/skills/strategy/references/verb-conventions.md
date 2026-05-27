# Verb Conventions — `/arcis:strategy`

Single source of truth for argument parsing, tool/Python envelope contracts,
agent dispatch, and the operator-facing error-envelope shape used by all
four verbs (`ideate`, `backtest`, `analyze`, `status`). Cited from
`commands/strategy.md`. Read-only.

---

## 4.1 Argument parsing convention

- `POSITIONAL_INPUT[0]` is the **verb** — required. Must be one of
  `ideate`, `backtest`, `analyze`, `status`. Anything else → §4.5 ERROR
  envelope `unknown verb: "<received>"`.
- `POSITIONAL_INPUT[1...]` is verb-specific (theme phrase / strategy-id /
  run-id / optional strategy-id for `status`).
- Flags are parsed BEFORE positional args, single-pass left-to-right:
  `--flag value` consumes two tokens; bare `--flag` (boolean) consumes one.
- Recognized flags:
  - `--quick` — boolean. For `backtest`: in-sample only (skip walkforward);
    surface ⚠ banner.
  - `--no-cross-domain` — boolean. For `ideate`: skip Wave B
    (research-cross-domain-analyst).
  - `--run-id <id>` — string. Continue/merge into a prior audit stream.
    Regex: `^(ideate|run)-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z-[0-9a-f]{6}$`.
  - `--out <path>` — string. For `ideate`: override default report path.
- Verb-missing or unknown verb → §4.5 ERROR envelope; STOP (no audit event).

## 4.2 Tool JSON envelope contract

All `python -m src.tools.<name> --json` invocations follow the FA16
universal envelope shape:

- **Success:** `{...verb-specific result fields...}` — body IS the result;
  no wrapper key.
- **Failure:** `{"error": {"type": "...", "message": "...", "tool": "..."}}`
  — top-level `error` key indicates failure.

The orchestrator checks `"error" in result` to branch. On error: surface
`error.message` verbatim in the §4.5 envelope (do NOT paraphrase); the
`tool` field is surfaced in the error-envelope post-amble.

## 4.3 Python-inline subprocess contract

For backtest engine + walkforward runner orchestration, the skill invokes
Python via heredoc subprocess: `python - <<'PY' ... PY`. Heredoc is chosen
over `python -c "..."` because blocks span 30-80 lines. The Python writes
a JSON envelope to stdout matching §4.2.

**Heredoc safety (per spec §9.4):**

```bash
# CORRECT — single-quoted delimiter; operator input via env var:
STRATEGY_ID="$STRATEGY_ID" python - <<'PY'
import os
sid = os.environ["STRATEGY_ID"]
...
PY

# WRONG — unquoted heredoc interpolates; leaks shell-meta on operator typo:
python - <<PY
sid = "$STRATEGY_ID"
PY
```

Rules (inherited from #109 DA3 fix):

- Heredoc delimiter MUST be single-quoted (`<<'PY'`).
- Operator-controlled strings (`STRATEGY_ID`, `THEME`, `RUN_ID`, etc.)
  MUST be passed via env vars or stdin, NEVER inline interpolated into
  Python source. The heredoc reads via `os.environ` ONLY.

## 4.4 Agent dispatch convention

Agent dispatch is via `Agent(subagent_type: "<name>", prompt: <DYNAMIC CONTEXT>)`.
The orchestrator parses registered output tags: `<db_report>` (db-investigator),
`<git_report>` (git-historian), `<findings>` (research-domain-lead and
research-cross-domain-analyst).

Dispatch waves (used by `ideate` only — `backtest`, `analyze`, `status`
dispatch no agents):

- **Wave A — parallel.** db-investigator + git-historian +
  research-domain-lead dispatched in a single message with three
  `Agent(...)` blocks. Wall-clock budget: 8 minutes.
- **Wave B — serial after Wave A.** research-cross-domain-analyst
  dispatched ONLY after Wave A returns (its DYNAMIC CONTEXT requires
  `DOMAIN_REPORTS` from completed leads). Skipped if `--no-cross-domain`.
  Wall-clock budget: 5 minutes.

Failure modes (each surfaces as a numbered finding; the verb proceeds
with remaining agents): agent returns no output tag → SOURCE FAILURE;
agent dispatch errors at the tool layer → SOURCE FAILURE; agent exceeds
orchestrator budget → `source: agent_timeout`.

If `research-domain-lead` fails to return ≥1 `key_finding` within Wave
A's budget, `ideate` refuses to synthesize and emits the §10.15
INCOMPLETE envelope (see `error-envelopes.md`).

## 4.5 Error envelope shape (operator-facing)

Every operator-facing error follows a uniform shape. Full per-class
examples live in `error-envelopes.md` (§10); the shape itself is:

```
<REFUSE | ERROR> — <verb>: <one-line summary>
  $REASON_OR_DETAIL
  $RESOLUTION_HINT

<post-amble: state about what was/wasn't mutated; audit event id written>
```

Conventions:

- **`REFUSE`** = skill chose not to act (policy gate: prod-PG sentinel,
  R8 firewall preflight). No mutation attempted.
- **`ERROR`** = attempted action failed (spec resolution, engine raise,
  runner raise, audit write).
- One-line summary ≤80 chars; names the verb explicitly for grep.
- Post-amble MUST state what was/wasn't mutated and the audit event name
  written (or "no audit event written" if the failure preceded audit start).
