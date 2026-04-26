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
// array AND src/version.py in the same commit. Sprint 0 Wave 1a F-CHANGELOG
// (PR #690 review B3) — refresh after months-old v0.25.0 was still showing.
const RECENT_ENTRIES = [
  {
    version: "v0.27.1",
    date: "2026-04-26",
    changes: [
      "PR #690 review sweep merged — 27 findings closed (5 Blockers + 8 Important + 14 Observations)",
      "Sprint 0 Wave 1a frontend cockpit: F-AUTH (Rules of Hooks) + F-CHANGELOG refresh",
      "Decision 6: KPI traffic-light thresholds aligned to audit-spec §3.1",
    ],
  },
  {
    version: "v0.27.0",
    date: "2026-04-25",
    changes: [
      "Track 1.5 instrumentation gap closure (B1–B9): exit slippage, broker_exceptions, exit_reason taxonomy, LLM Key Risk + timeout persistence, instrumentation_version sentinel",
      "Round 8.A–F dashboard fixes: 5-KPI hero strip + broker_exceptions panel + preflight UI echo",
      "Round 10 zero-failures cleanup (Fix-A/B/C/D, anti-gaming verified)",
      "SD#46 fix-everything-technically-before-trading principle adopted; Mon $100 deploy deferred post-Cohort-3",
    ],
  },
  {
    version: "v0.26.0",
    date: "2026-04-23",
    changes: [
      "Exit-overshoot cancel-race fix (#608/#609/#610, PR #636) — _handle_pre_exit_cancel routes to _close_from_broker_fill on cancel-fill race",
      "CVS retry loop + phantom exits (PR #595): D2 reconcile branch + D3 executor qty sync + _strip_enum normalization",
      "Council fail-closed (#612, PR #636): ClaudeAuthError + CouncilUnavailableError replace silent fake 5-0 consensus",
      "Triage bundle: 29 issues closed across 4 tiers; src/version.py single source of truth (#631-15)",
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
