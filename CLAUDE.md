# CLAUDE.md — rules every agent session reads first

- Read SCOPE.md first. The ledger in §3 is the boundary: if a component is not listed as CORE and Active, it does not get built.
- Work only the tasks in the current sprint file (`docs/sprints/`). If something seems to need work outside the sprint's scope, stop and write it in the sprint report.
- Never invent a value, a rule, or a result. Record it as `UNRESOLVED` and ask.
- Code rules: Python 3.12, no source file over 400 lines, no function over 60 lines, no blind exception handling, typed errors, fail-closed configuration, tests with every task.
- Never commit credentials, market data, news article text, personal records, or large binaries. The repository is public.
- Branch naming `feat/sNN-slug`, one sprint per branch, the PR template checklist must pass, and every sprint updates the README documentation map (if it added a document), the roadmap row of any step it closes, the CHANGELOG, and its own sprint report.
- Run `uv run python tools/checks.py` before opening a PR; it runs exactly what CI runs.
