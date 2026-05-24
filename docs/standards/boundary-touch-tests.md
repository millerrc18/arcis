# Boundary-Touch Test Discipline

**Status:** Mandatory for PR reviewers and coding agents | **Owner:** Reviewers/PMs | **Since:** v0.36.59 (#103) | **Replaces:** ad-hoc "test the seam" convention

A discipline-level standard for catching the **mock-coverage-gap class** of bugs that AI-generated code disproportionately produces. Three v0.36.5x cutover hotfixes (`v0.36.51` gpu_placement_smoke field bug, `v0.36.52` watchdog model-tag + safe_send kwargs, `v0.36.53` boundary-touch tests for the safe_send fix) were all the same shape: tests passed cleanly, but never actually exercised the seam where the bug lived. The discipline is meant to catch every member of that family at review time.

This doc is cited by:
- `.claude/plugins/arcis/agents/coding-qa-reviewer.md` — workflow step 3 (Test rigor check)
- `.claude/plugins/arcis/agents/coding-security-reviewer.md` — sibling-search step
- `.claude/plugins/arcis/agents/coding-rigor-reviewer.md` — rubric C5 (Test honesty)

---

## 1. What is a boundary-touch test?

A **boundary-touch test** exercises the *seam* between two components — where one component's implementation can drift from another component's expectation without anyone noticing.

The bug class this catches: code on each side of the seam passes its own unit tests, but the seam itself is mocked or stubbed in both test suites, so neither side ever drives the real contract. Result: the contract drifts, both sides "pass," production breaks.

Common seams:
- **Mock target vs real call site** — `@patch("src.X.Y.Z")` works only if production code actually calls `X.Y.Z` at that import path. Rename the import path → patch silently no-ops → test still "passes."
- **Mock signature vs real signature** — `safe_send = MagicMock()` accepts any kwargs. Production sends `safe_send(message=...)`; the real function expects `event=...`. Tests pass; production crashes.
- **Mock data shape vs real producer** — fake fixture has `gpu_index` field; real `nvidia-smi` query returns `gpu_uuid`. Tests pass with the fake; production hits `Field "gpu_index" is not a valid field`.
- **Schema source-of-truth drift** — two files define the "same" constant (e.g., `_PROD_SIGNATURES` in both `prod_guard.py` and `arcis_config.yaml`). Drift between them = the cross-cutting invariant breaks silently.
- **Decorator composition** — three decorators stacked on a function each unit-test cleanly; their *interaction* (exception class detection, log ordering, scope of side-effects) only fails when composed.

**A boundary-touch test drives both sides of the seam with real artifacts.** No mocks at the seam itself. The test asserts on the OUTPUT of the contract (e.g., the actual log file contents, the actual return value, the actual database state), not on whether a mock was called.

### Canonical positive example (v0.36.57 #104, `tests/tools/test_safe_op_integration.py`)

The tooling-foundation PR built `@safe_op` + `@safety_window` + `@prod_guard` decorators. Each had its own unit tests with mocks — straightforward. The keystone boundary-touch test composed all three on a real fake tool and drove it through 5 terminal states:

```python
@safe_op(name="fake_restart", mutates=True, log_path=log)
@safety_window("no_restart_overnight", now_et=fake_clock, log_path=log)
@prod_guard(dsn_param="dsn", log_path=log)
def fake_restart(service: str, dsn: str, *, confirm: bool = False, emergency: bool = False):
    call_count["n"] += 1
    return f"restarted {service}"

# Then drive through dry_run / safety_block / prod_block / confirmed_success / emergency_bypass
# and assert on REAL audit-log file contents at each step.
```

The keystone invariant — "SafetyError from inner guard does NOT double-log via safe_op's except clause" — is the kind of contract that single-primitive tests would miss. Only composing the real decorators in real order exercises it.

---

## 2. The vacuous-test anti-pattern

A **vacuous test** is one that passes regardless of the implementation under test. It mocks the failure mode (`side_effect=Exception`) or asserts the negative (`_not_called()`), but never drives the state machine into the branch that would trigger the assertion. The test is theater — it locks no regression because it can't catch its own regression.

### Two real cases (memory: `feedback_vacuous_test_pattern`)

**#94 T1 — `ollama_watchdog.test_ensure_owner_empty_store_not_healthy`** (2026-05-22)

```python
@patch("src.scheduler.ollama_watchdog.preflight_check")
def test_ensure_owner_empty_store_not_healthy(self, mock_pre):
    # Setup an empty model store...
    result = ensure_owner()
    assert result is False  # ← but does this ever fail without the impl?
```

The test patched `mock_pre` but never asserted it was called. A regression where `ensure_owner` silently adopts an empty-store Ollama (the v0.36.47 failure shape) would have still passed because the assertion didn't depend on `preflight_check` running.

**Fix:** add `mock_pre.assert_called_once()` + verify the empty-store path is actually taken.

**#94 T18 — `watchdog_liveness_monitor.test_tick_does_not_raise_when_metric_check_raises`** (2026-05-22)

```python
sc_query.return_value = True  # ← always "service running"
metric_helper.side_effect = RuntimeError("kaboom")
tick()  # expected to swallow the RuntimeError
```

But `metric_helper` is only called in the NOT-RUNNING branch. Setting `sc_query=True` means the metric helper never fires → the `RuntimeError` never raises → the test passes regardless of whether the impl actually catches the exception.

**Fix:** drive `sc_query=[True, False]` across two ticks so the NOT-RUNNING branch is exercised, then verify the impl's try/except catches the RuntimeError.

### Detection rubric for reviewers

For any test whose purpose is "verify the guard fires," ask the **gold-standard question**:

> "Would this test fail if the implementation under test were deleted?"

If the answer is **no** (or "I don't know"), the test is vacuous. Either fix it (drive the state machine into the branch first, THEN trigger the fail-mode mock) or reject the PR.

**Empirical gold-standard proof:** in a subprocess, temporarily remove the guard (the `try/except`, the `if` check, whatever) and re-run the test. If the test still passes, it was vacuous. The developer who lands T18's fix verified non-vacuousness this way — that's the standard to imitate.

---

## 3. Sibling-search principle

Memory: `feedback_review_sibling_search`. The discipline-correct re-statement:

> When a bug is found at `file:line`, the next step is NOT to fix-and-move-on. It is to grep the file for the same anti-pattern at other lines BEFORE declaring the fix complete.

Surfaced from PR #690 (Dashboard.jsx:443 broken template literal at line 443, identical bug at line 445 missed by the first reviewer) and re-validated repeatedly since.

**Strong form for module-deletion / symbol-renames** (PR #1055):

```bash
grep -rn -E "from src\.X|import src\.X|src\.X\." tests/ src/ --include="*.py" \
  | grep -v "test_<regression_lock_file>"
```

The three-form regex catches `from src.X.Y import ...`, `from src.X import Y`, and dotted-attribute-string references (used in `@patch` decorators, log strings, docstrings) — all three got missed by the simpler single-form grep historically.

**Strong form for decorator-composition / contract drift** (v0.36.57 #104):

When a single-source-of-truth invariant exists (e.g., `_PROD_SIGNATURES` in `src/simulation/lifecycle/prod_guard.py` mirrored in `config/arcis_config.yaml`'s `pg.prod_dsn_signatures`), the boundary-touch test that asserts equality between them IS the sibling-search done preemptively. The test:

```python
def test_load_arcis_config_pg_signatures_match_prod_guard():
    from src.simulation.lifecycle.prod_guard import _PROD_SIGNATURES
    from src.tools._config import load_arcis_config
    cfg = load_arcis_config()
    assert set(cfg.pg.prod_dsn_signatures) == set(_PROD_SIGNATURES)
```

If someone edits one without the other, the test fails immediately and forces them to confront the drift. This is the canonical sibling-search-as-test pattern.

---

## 4. Reviewer's pre-merge checklist

A PR with new or modified tests is APPROVE-able only when:

1. **Mock target resolution**: every `unittest.mock.patch("X.Y.Z")` introduced resolves to an actual import path in production code. Verify with `grep -rn "X.Y.Z" src/`. If zero hits, the patch silently no-ops → BLOCKER.

2. **Method/attribute name resolution**: every `obj.method_name()` and `MyClass.method_name` referenced in new tests exists on the actual class. Verify with `grep "def method_name" src/`. If absent → BLOCKER.

3. **Vacuous-test detection**: for any test whose purpose is "verify the guard fires" (asserts `_not_called`, uses `side_effect=raise`, covers a fail-soft branch), ask the gold-standard question. If the answer is unclear, reject with a request to prove non-vacuousness (subprocess-remove-impl-and-rerun).

4. **Boundary-touch coverage**: when the PR introduces composed contracts (decorators, multi-module pipelines, schema mirrors), at least one test exercises the FULL contract end-to-end with real artifacts — NOT mocks at the seam.

5. **Sibling-search disclosed**: when the PR fixes a bug at `file:line`, the PR description or commit message documents what was grepped and what was found. Reviewer re-runs a sample search to verify.

6. **Standards-doc citation**: when the PR introduces a NEW boundary-touch test (the canonical `tests/tools/test_safe_op_integration.py` pattern), the test's module docstring cites this standards doc URL so future readers understand the discipline applied.

---

## 5. When this discipline applies

| Situation | Apply? |
|---|---|
| New decorator/wrapper/middleware | YES — composed contracts have unit-test blind spots |
| New mock fixture for an external API | YES — mock signature ≠ real signature is the most common AI defect |
| New source-of-truth file mirroring another | YES — drift between mirrors is the textbook sibling-search target |
| Schema/registry edit | YES — adjacent rows often have the same anti-pattern |
| Pure refactor (no behavior change) | NO — discipline applies to BEHAVIORAL changes |
| Comment/docs-only PR | NO — no test surface, no boundary |
| Single-line bug fix WITHOUT new test | YES, partially — sibling-search applies even without new tests |

---

## 6. References

- Memory: [feedback_vacuous_test_pattern](../../) — gold-standard question + empirical verification
- Memory: [feedback_review_sibling_search](../../) — three-form grep regex + PR #690 origin
- Memory: [feedback_strict_rigor_no_handwave](../../) — operator-stated "rather take a full day than hand wave"
- v0.36.51 CHANGELOG — `gpu_index` mock-coverage gap (canonical example case 1)
- v0.36.52 CHANGELOG — model-tag fallback + safe_send kwargs (case 2 — fixed in v0.36.53)
- v0.36.57 CHANGELOG — `tests/tools/test_safe_op_integration.py` (canonical positive example)
