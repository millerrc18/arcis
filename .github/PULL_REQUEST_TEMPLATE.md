## Boundary-touch self-check

Every PR that adds or modifies tests MUST satisfy this 6-item checklist (canonical text: [`docs/standards/boundary-touch-tests.md`](../docs/standards/boundary-touch-tests.md)):

- [ ] **Mock target resolution** — grep the codebase for each `@patch(...)` import path; every patch resolves to a real callable.
- [ ] **Method/attribute name resolution** — every asserted `obj.method` / `MyClass.attr` exists on the real type.
- [ ] **Vacuous-test detection** — for every new test, answer the gold-standard question: "would this test fail if the implementation under test were deleted?" If unclear, prove non-vacuousness empirically.
- [ ] **Boundary-touch coverage** — for any composed contract (stacked decorators, multi-callee pipelines, schema mirrors), at least one test drives the real boundary end-to-end — no mocks at the seam.
- [ ] **Sibling-search disclosure** — when fixing a bug at `file:line`, the PR description names the sibling files searched for the same anti-pattern ("none found" is acceptable when searched).
- [ ] **Standards citation** — new boundary-touch tests cite [`docs/standards/boundary-touch-tests.md`](../docs/standards/boundary-touch-tests.md) in their module/test docstring.

---

## Summary

<!-- 1-3 bullets on what this PR does and why. -->

## Changes

<!-- List of files changed and the user-visible behavior change. Reference issues / specs as relevant. -->

## Test plan

<!-- Bulleted checklist of how this PR was verified. Include test output / counts when relevant. -->

- [ ] `pytest tests/ -q` PASS (count ≥ 5,467)
- [ ] `pytest tests/test_repo_structure.py -v` PASS
- [ ] Visual-verify performed (if frontend touched)
- [ ] NSSM smoke-test performed (if `watch.py` or `src/api/*.py` touched)

## Rollout / rollback notes

<!-- Anything operator-runnable: schema migrations, env-var changes, NSSM service restarts, embargo windows, revert steps. -->
