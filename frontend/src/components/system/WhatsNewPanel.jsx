/**
 * "What's New" panel — shows the most recent CHANGELOG entries.
 * Static rendering in v1 (no CHANGELOG parser endpoint exists yet);
 * uses a hardcoded slice of the [Unreleased] section as the content.
 * v1.1 will move this to a parsed API endpoint.
 *
 * Surfaces recent work so the operator (and future AI sessions) see
 * what has changed since last reading the docs.
 */

// Mirror of the most recent CHANGELOG.md entries. Three most recent versions,
// most-recent first. When you cut a release, update CHANGELOG.md AND this
// array AND src/version.py in the same commit (per docs/versioning-policy.md).
// Sprint 0 Wave 1a F-CHANGELOG (PR #690 review B3) flagged this — refresh
// after stale v0.25.0 was rendering. Refreshed at v0.32.0 retroactive cut.
const RECENT_ENTRIES = [
  {
    version: "v0.32.0",
    date: "2026-04-29",
    changes: [
      "Sprint 1.C Phase 1 attribution discipline (#846/#847/#848) — canonical llm_action validator + conviction-band scale fix + coverage-drop postmortem",
      "Sprint 1.C Phase 2 LLM-prompt PIT audit (#94) — 11 prompt sections audited; 5 PIT-broken HIGH severity; Stage 1 start may need 2014→2022 revision",
      "8 PIT follow-up trackers filed (#854-#861) for Phase 4 corpus prerequisites",
    ],
  },
  {
    version: "v0.31.0",
    date: "2026-04-28",
    changes: [
      "Walk-forward harness (#78) — anchored expanding × 8 folds × 21-day embargo; underpowered-fold filter <15 trades",
      "Methodology wiring: cost-model calibration (#79) + FRED rf-rate (#80) + promotion gate (#49) + subgroup analysis harness (#81)",
      "Pre-registration document (#63) — binding methodology contract per §5.3",
      "Pre-push git hook (#59) — refuses pushes from branches behind origin/main; closes stale-base hazard class (5 incidents)",
    ],
  },
  {
    version: "v0.30.0",
    date: "2026-04-28",
    changes: [
      "Reconcile track (#68-#74): 623,360 ghost rows deleted across 25 tables in three passes (Render Postgres delete-replication gap)",
      "Dashboard sprint Tier 1.A-1.F (#54): orphan cloud routes wired, CORS env var documented, /api/commands/expire-stale + COALESCE outcome query, registry imports on startup",
      "TableDef.sync_reconcile registry-driven allowlist (#73); periodic reconcile in run_sync_cycle (#72)",
    ],
  },
  {
    version: "v0.29.0",
    date: "2026-04-27",
    changes: [
      "Sprint 1.A.x point-in-time SP100 universe (#794-#821): Wikipedia scraper + JSON backfill + curated corp-action history",
      "Tier A: PCLN→BKNG, KRFT→KHC, UTX+RTN→RTX, EMC removal, YHOO removal. Tier B: CELG, S, FB→META",
      "T10 survivorship migration: backtest/sim/training-backfill use get_sp100_at(<as_of>); live runtime retains get_sp100_universe()",
      "Test baseline lifted 3671→3682 (T10 regression-locks +11)",
    ],
  },
  {
    version: "v0.28.0",
    date: "2026-04-26",
    changes: [
      "Sprint 0 wave-system: 14 parallel-dispatch PRs (#700-#724) — frontend cockpit, status constants, watch-loop discipline, schema floor, FRED rf v2, walkforward KPIs SE, Sharpe consolidation, promotion-gate methodology, live-order verification, PIT features",
      "Sprint 0.B-0.D triage: ~30 silent-failure / code-hygiene / connect-db / size / method findings closed",
      "Worktree-per-agent dispatch pattern formalized in CLAUDE.md (#699)",
    ],
  },
  {
    version: "v0.27.1",
    date: "2026-04-26",
    changes: [
      "PR #690 review sweep merged — 27 findings closed (5 Blockers + 8 Important + 14 Observations)",
      "Sprint 0 Wave 1a frontend cockpit: F-AUTH (Rules of Hooks) + F-CHANGELOG refresh",
      "Decision 6: KPI traffic-light thresholds aligned to audit-spec §3.1",
    ],
  },
];

export default function WhatsNewPanel() {
  return (
    <div className="bg-white dark:bg-slate-800 rounded shadow p-4 mb-4">
      <h3 className="text-sm font-semibold mb-3">What&apos;s New</h3>
      {RECENT_ENTRIES.map((entry) => (
        <div key={entry.version} className="mb-3 last:mb-0">
          <div className="text-xs font-medium text-gray-700 dark:text-gray-200 mb-1">
            {entry.version} <span className="text-gray-500">· {entry.date}</span>
          </div>
          <ul className="text-xs text-gray-600 dark:text-gray-400 list-disc pl-4 space-y-1">
            {entry.changes.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      ))}
      <div className="text-xs text-gray-500 mt-2">
        Full history in CHANGELOG.md
      </div>
    </div>
  );
}
