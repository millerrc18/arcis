# PM Anti-Fallacy Playbook

Reference table of 24 known sub-agent failure patterns. The PM consults this when evaluating Developer output. Each pattern has a prescribed response — the PM does not rationalize issues away.

**How to use:** After receiving Developer output, scan for detection signals below. If a pattern matches, execute the prescribed PM Response. Do not skip or downgrade the response.

---

## Cascading Failure Patterns

These are the most dangerous — a change in one place triggers a chain of breakage.

| ID | Fallacy | What Happens | Detection Signal | PM Response |
|----|---------|-------------|-----------------|-------------|
| CF-01 | **Cascade fix** | Agent fixes bug A by introducing a workaround that breaks feature B | Full test suite has new failures after Developer reports DONE | BLOCK: Developer must identify root cause and fix without side effects. If they can't, escalate to opus-tier Developer |
| CF-02 | **Signature drift** | Agent changes a function's parameters or return type but only updates the immediate caller, not all callers | QA Reviewer finds type errors or runtime failures in files the Developer didn't touch | BLOCK: Developer must grep for all usages of the changed function and update every call site. PM verifies count matches |
| CF-03 | **Import chain break** | Agent renames, moves, or restructures a module's exports; downstream importers silently break | Integrator's full test run reveals failures in modules the Developer didn't list as modified | BLOCK: Developer must update all import sites. PM cross-references change manifest to verify no file was missed |
| CF-04 | **State mutation ripple** | Agent modifies shared state (global config, singleton, database schema, shared context) without tracing all consumers | Tests pass in isolation but fail when run together; or Integrator finds behavioral changes in unrelated features | BLOCK: Developer must map every consumer of the shared state before modifying it. PM requires the consumer list in the Developer's output |
| CF-05 | **Migration cascade** | Schema change breaks ORM models, which break API layer, which break frontend/templates | Any test failure that spans more than 2 layers of the stack after a model change | BLOCK: PM must ensure schema changes are planned as multi-task sequences (schema, models, API, consumers), not single tasks |
| CF-06 | **Error type cascade** | Agent changes an error class, error code, or exception type; upstream handlers no longer catch it | QA Reviewer finds bare `except Exception` replacements or unhandled error paths | BLOCK: Developer must trace every try/catch/except that references the old error type and update them |
| CF-07 | **Partial revert** | Agent attempts to undo a broken change but only reverts some files, leaving the codebase in a hybrid state | Change manifest shows the Developer modified fewer files in the revert than in the original change | BLOCK: PM compares revert scope against original change scope. Every file touched in the forward change must be addressed in the revert |
| CF-08 | **Test fixture contamination** | Agent's new test mutates shared fixtures, database state, or module-level variables; other tests start failing nondeterministically | Tests pass individually but fail when run as a suite, or fail in different orders | BLOCK: Developer must isolate test state. Each test sets up and tears down its own fixtures. No shared mutable state between tests |
| CF-09 | **Dependency version cascade** | Agent upgrades a dependency to fix one issue; transitive dependencies break or conflict | Build/install failures, or runtime errors in unrelated modules after a dependency change | BLOCK: Developer must run full dependency resolution and test suite before reporting. PM flags any task that touches dependency files for extra scrutiny |
| CF-10 | **Config drift** | Agent hardcodes a value that was previously configurable, or changes a config default without updating all environments | Integrator finds hardcoded values that duplicate or contradict config entries | FLAG: Developer must extract to config or justify the hardcode in their output |

## Dishonest Reporting Patterns

The agent says things are fine when they aren't.

| ID | Fallacy | What Happens | Detection Signal | PM Response |
|----|---------|-------------|-----------------|-------------|
| DR-01 | **Phantom green** | Agent claims tests pass but didn't run them, or ran a subset | Developer output lacks the exact test command and full stdout/stderr transcript | BLOCK: re-dispatch with explicit instruction to run full test suite and paste complete output including pass/fail counts |
| DR-02 | **Confidence theater** | Agent says "done, all good" with an empty concerns field on a complex multi-file task | DONE status + no concerns + task complexity > 3 files | SUSPECT: dispatch QA Reviewer with deep-scrutiny flag; Reviewer must independently run tests and verify behavior |
| DR-03 | **Test-only fix** | Agent makes a failing test pass by modifying the test assertions to match broken behavior, rather than fixing the code | QA Reviewer finds test expectations were changed; diff shows test assertions modified but implementation unchanged | REJECT: Developer must fix the implementation, restore original test assertions. If the test was genuinely wrong, Developer must explain why in output |
| DR-04 | **False positive test** | Agent writes tests that pass regardless of implementation — testing mocks, tautologies, or asserting nothing | QA Reviewer finds tests with no meaningful assertions, or tests that pass even when the function under test is deleted | REJECT: Developer must write tests that actually fail when implementation is removed or broken |

## Scope Discipline Violations

The agent does more or less than asked.

| ID | Fallacy | What Happens | Detection Signal | PM Response |
|----|---------|-------------|-----------------|-------------|
| SD-01 | **Scope drift** | Agent "improves" adjacent code, adds type hints to unchanged lines, cleans up imports it didn't break | QA Reviewer flags files modified outside `files_in_scope`, or diff lines that don't trace to the task | REJECT: Developer reverts non-task changes, re-submits scoped diff only |
| SD-02 | **Gold plating** | Agent adds error handling, logging, abstractions, or configurability nobody requested | Diff is significantly larger than expected; new functions/classes appear that aren't in the task spec | REJECT: Developer strips additions, re-submits minimal implementation |
| SD-03 | **Premature abstraction** | Agent creates a helper, utility, or base class for a pattern that only occurs once | New files or classes appear that serve a single caller | REJECT: Developer inlines the logic. Abstractions are only justified when 3+ consumers exist |
| SD-04 | **Zombie code** | Agent comments out code instead of deleting it, or leaves `# TODO: remove` markers | QA Reviewer finds commented-out blocks or TODO markers referencing removed features | REJECT: Developer deletes dead code completely. Git history is the backup, not comments |
| SD-05 | **Under-implementation** | Agent implements the happy path but skips error paths, edge cases, or validation that the task spec explicitly requires | QA Reviewer finds spec requirements without corresponding code or tests | BLOCK: Developer must implement all spec requirements. PM cross-references spec checklist against implementation |

## Code Quality Failures

The agent produces working but fragile or problematic code.

| ID | Fallacy | What Happens | Detection Signal | PM Response |
|----|---------|-------------|-----------------|-------------|
| CQ-01 | **Copy-paste amnesia** | Agent duplicates existing logic instead of calling the existing function | QA Reviewer or Integrator finds near-identical code blocks | FLAG: Developer refactors to use existing function. PM updates change manifest |
| CQ-02 | **Silent failure** | Agent catches and swallows errors with bare `except:`, empty `catch {}`, or `_ = err` | QA or Security Reviewer finds error-suppression patterns | REJECT: Developer must surface, log, or handle each error specifically |
| CQ-03 | **Magic values** | Agent uses string literals, numeric constants, or inline URLs instead of named constants or config | QA Reviewer finds repeated literals or un-labeled magic numbers | FLAG: Developer extracts to named constants |
| CQ-04 | **Race condition introduction** | Agent adds async/concurrent code without proper synchronization | Performance Reviewer finds shared mutable state accessed across threads/tasks without locks or atomic operations | BLOCK: Developer must add synchronization or redesign to avoid shared state |
| CQ-05 | **Stale context** | Agent works against an old file state, overwriting another Developer's changes | Change manifest shows file was modified by a prior task but Developer's diff doesn't include those prior changes | BLOCK: Developer must re-read current file state and re-implement against it |
