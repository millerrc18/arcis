/**
 * "What's New" panel — shows the most recent CHANGELOG entries.
 * Static rendering in v1 (no CHANGELOG parser endpoint exists yet);
 * uses a hardcoded slice of the [Unreleased] section as the content.
 * v1.1 will move this to a parsed API endpoint.
 *
 * Surfaces recent work so the operator (and future AI sessions) see
 * what has changed since last reading the docs.
 */

const RECENT_ENTRIES = [
  {
    version: "v0.25.0",
    date: "2026-04-18",
    changes: [
      "Capability Registry + /api/system/index (Sprint 1B)",
      "Diagnostic Dashboard: /diagnostics page with regime + forensic kickoff (Sprint 1A)",
      "Walk-forward validation framework + promotion gate enforcement (PBO / OOS)",
    ],
  },
  {
    version: "v0.24.0",
    date: "2026-03-15",
    changes: [
      "Strategy Research Platform final: find_candidates integration + /research-platform page",
      "Python plugin strategy interface + register_plugin decorator",
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
