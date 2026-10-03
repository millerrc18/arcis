<!-- PR checklist for the arcis rebuild. Every box must be ticked before merge. -->

## Sprint

- [ ] Sprint file and task list linked (e.g. `docs/sprints/S01-news-recorder.md`, T1–T10).

## Charter compliance

- [ ] Ledger row exists in SCOPE.md §3 and is marked Active.
- [ ] Nothing from the sprint's Out list appears in the diff.
- [ ] No file over 400 lines, no function over 60 lines.

## Hygiene (I-16)

- [ ] No credentials, market data, news article text, or personal records added.
- [ ] Any `# hygiene: allow` pragma is justified below.

## Verification

- [ ] `uv run python tools/checks.py` passes locally (ruff, mypy, ledger/size/hygiene checks, pytest).

## Documentation

- [ ] README documentation map updated (if a document was added).
- [ ] Roadmap row of any closed step dated.
- [ ] CHANGELOG.md updated.
- [ ] Sprint report appended to the sprint file.

## Hygiene pragma justifications

<!-- List each `# hygiene: allow` / `<!-- hygiene: allow -->` in the diff and why it is needed. -->
