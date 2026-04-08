# Master Sprint Queue: 6 Unimplemented Specs

> **Operator:** CC (Claude Code)
> **Orchestrator:** Ryan Miller
> **Estimated total time:** 25-35 hours CC time across 6 sprints
> **Execution:** Sequential. Do NOT start Sprint N+1 until Sprint N is merged.

---

## Instructions for CC

You have 6 sprint specs in `docs/sprints/` that have been designed and Ralph-looped
but never implemented. Execute them in the order below.

**For EACH sprint:**

1. **Read the spec first.** `cat docs/sprints/{sprint-file}.md` — read the ENTIRE doc
2. **Audit the spec against current codebase.** The specs were written at various
   points between v0.10.0 and v0.15.0. The codebase is now at v0.16.0 with 212
   Python files, 123 test files, and 21 dashboard pages. File paths, import
   locations, and function signatures may have changed. Before implementing:
   - Verify every file path in the spec still exists
   - Verify every import path is correct
   - Verify every function/class reference matches the current code
   - If something has moved or changed, adapt the implementation to match
     the current codebase — do NOT blindly follow stale paths
3. **Read MASTER.md** for current system state
4. **Create a feature branch:** `git checkout -b feat/{branch-name}`
5. **Run pre-flight:** `python -m pytest tests/ -x -q` — record baseline count
6. **Implement all tasks** following the spec, adapting as needed for v0.16.0
7. **Run post-flight:**
   - `python -m pytest tests/ -x -q` — count must not decrease
   - `cd frontend && npm run build && cd ..` — must succeed
   - No new src/ file over 400 lines
   - No function over 60 lines
8. **Update docs:**
   - MASTER.md Section 2 (volatile counts)
   - CHANGELOG.md
   - RELEASES.md (if tagged)
9. **Push to feature branch:** `git push origin feat/{branch-name}`
10. **Do NOT merge to main.** Ryan will review and merge.

---

## Sprint Queue (execute in this order)

### Sprint 1: System Monitoring
- **File:** `docs/sprints/sprint-system-monitoring.md`
- **Branch:** `feat/system-monitoring`
- **Priority:** HIGH — addresses operational blind spots (stale collectors,
  stuck commands, no uptime visibility)
- **Estimated:** 5-7 hours
- **Key deliverables:** src/monitoring/ directory (3 collectors), 3 new DB
  tables, 4 API endpoints, Monitoring.jsx dashboard page
- **Codebase notes:** watch.py is now 1,968 lines (was 3,403 when spec
  written). The periodic collection trigger should go in the main loop
  around line 1580, near the Telegram polling block. The spec references
  `src/api/routes/system.py` but cloud routes are in
  `src/api/cloud_routes/` — adapt accordingly.

### Sprint 2: React Flow UI Polish
- **File:** `docs/sprints/sprint-react-flow-ui-polish.md`
- **Branch:** `feat/react-flow-polish`
- **Priority:** MEDIUM — visual polish for existing pages
- **Estimated:** 3-4 hours
- **Key deliverables:** Enhanced Architecture + Schema diagram pages,
  UI polish across dashboard
- **Codebase notes:** Architecture.jsx and Schema.jsx already use React
  Flow (added in mega sprint). The spec may describe building these from
  scratch — skip anything that already exists, focus on POLISH and
  enhancements only. Check existing pages before implementing.

### Sprint 3: XML Expansion (7→11 sections)
- **File:** `docs/sprints/sprint-xml-expansion.md`
- **Branch:** `feat/xml-expansion`
- **Priority:** MEDIUM — needed before v2 training data spec
- **Estimated:** 3-4 hours
- **Key deliverables:** 4 new XML sections in LLM output (options flow,
  sector RS, event calendar, cross-asset), random source subsetting
- **Codebase notes:** The LLM prompts are in `src/llm/prompts.py`. The
  packet writer is `src/llm/packet_writer.py`. Training data collector
  is `src/training/data_collector.py`. The feature engine is
  `src/features/engine.py`. All paths should be current.

### Sprint 4: Research Framework
- **File:** `docs/sprints/sprint-research-framework.md`
- **Branch:** `feat/research-framework`
- **Priority:** MEDIUM — documentation synthesis
- **Estimated:** 3-4 hours
- **Key deliverables:** Master research document synthesizing 65 research
  docs into a single framework
- **Codebase notes:** This is primarily a documentation task. Research
  docs are in `docs/research/`. The output goes to
  `docs/research/ARCIS_RESEARCH_FRAMEWORK.md`.

### Sprint 5: IB Integration
- **File:** `docs/sprints/sprint-ib-integration.md`
- **Branch:** `feat/ib-integration`
- **Priority:** LOW — gated by Strategy Decision #25 (requires 60+ trades,
  Sharpe >1.0, 30-day Gateway stability test)
- **Estimated:** 8-12 hours
- **Key deliverables:** IB broker adapter, Gateway health monitor,
  shadow mode (mirror Alpaca trades on IB paper)
- **Codebase notes:** The broker abstraction layer was built in v0.14.0
  (`src/shadow_trading/alpaca_adapter.py` is the reference implementation).
  IB adapter should follow the same interface. The spec is 1,060 lines
  and very detailed — follow it closely. Wire to IB PAPER (port 4002)
  only, never live (port 4001).
- **IMPORTANT:** This sprint builds the infrastructure only. Do NOT
  enable IB live trading. That requires Ryan's explicit approval after
  the SD#25 validation gate passes.

### Sprint 6: iOS Capacitor App
- **File:** `docs/sprints/sprint-ios-capacitor.md`
- **Branch:** `feat/ios-capacitor`
- **Priority:** LOW — quality of life, not blocking Phase 1
- **Estimated:** 4-6 hours CC time + 30 min Ryan in Xcode
- **Key deliverables:** Capacitor wrapper, iOS project config, push
  notifications, biometric auth
- **Codebase notes:** Requires macOS with Xcode 15+ for final build.
  CC can scaffold everything and create the Capacitor config, but the
  actual Xcode build/signing must happen on Ryan's Mac. If CC doesn't
  have macOS access, implement everything except the Xcode-specific
  steps and document what Ryan needs to do locally.

---

## Global Rules

1. **File size limit:** No src/ file over 400 lines. If a new file would
   exceed this, split it into logical sub-modules.
2. **Function length:** No function over 60 lines.
3. **Backward compatibility:** Never break existing tests. Never remove
   existing API endpoints. Never change function signatures without
   updating all callers.
4. **Import paths:** Use lazy imports (import inside function) for
   optional dependencies. Use module-level imports for core deps.
5. **Error handling:** Every external call (subprocess, HTTP, database)
   must be in try/except. Graceful degradation over crashes.
6. **Testing:** Every new module needs tests. Minimum: happy path +
   error path + edge case. Test file naming: `tests/test_{module}.py`.
7. **Sync:** New tables that should be visible on the cloud dashboard
   need `sync_to_postgres=True` in the schema registry.
8. **Frontend:** Use existing Arcis design system (CSS variables in
   index.css). Bloomberg dark theme. Monospace for numbers. No external
   CSS frameworks beyond Tailwind.

---

## After All 6 Sprints

Once all branches are pushed and reviewed:
- Merge all 6 feature branches to main (resolve conflicts in order)
- Tag as v0.17.0 (or appropriate version)
- Run full test suite one final time
- Update MASTER.md with final counts
- Run `scripts/verify_docs.py` to check for drift
