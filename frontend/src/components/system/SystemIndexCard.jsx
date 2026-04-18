/**
 * Single capability card. Shows name + 1-sentence description + current
 * state (when applicable) + action affordances (kickoff for Action,
 * Mark Reviewed for stale).
 */
function stateStatus(entry) {
  if (entry.kind === "action" || entry.kind === "decision") return null;
  if (entry.kind === "state") return entry.live?.status;
  if (entry.kind === "system") return entry.health?.status;
  return null;
}

function statusColor(status) {
  if (status === "ok") return "bg-green-100 text-green-700";
  if (status === "degraded") return "bg-yellow-100 text-yellow-800";
  if (status === "down") return "bg-red-100 text-red-700";
  if (status === "timeout") return "bg-yellow-100 text-yellow-800";
  if (status === "unavailable") return "bg-gray-100 text-gray-600";
  return "bg-gray-100 text-gray-700";
}

function daysSince(isoDate) {
  if (!isoDate) return null;
  const then = new Date(isoDate);
  const diff = Date.now() - then.getTime();
  return Math.floor(diff / (1000 * 60 * 60 * 24));
}

export default function SystemIndexCard({ entry, onOpenDetail }) {
  const status = stateStatus(entry);
  const effectiveReviewed = entry.last_reviewed_date_override || entry.last_reviewed_date;
  const stale = daysSince(effectiveReviewed) > 180;
  return (
    <button
      type="button"
      onClick={() => onOpenDetail?.(entry)}
      className="text-left border border-gray-200 dark:border-slate-700 rounded p-3 hover:bg-gray-50 dark:hover:bg-slate-700 transition"
    >
      <div className="flex justify-between items-start mb-1">
        <div className="font-medium text-sm">{entry.name}</div>
        <div className="flex gap-1">
          {status && (
            <span className={`text-xs px-2 py-0.5 rounded ${statusColor(status)}`}>
              {status}
            </span>
          )}
          {entry.deprecated && (
            <span className="text-xs px-2 py-0.5 rounded bg-red-100 text-red-700">
              deprecated
            </span>
          )}
          {stale && (
            <span className="text-xs px-2 py-0.5 rounded bg-orange-100 text-orange-700">
              review
            </span>
          )}
        </div>
      </div>
      <div className="text-xs text-gray-600 dark:text-gray-300 line-clamp-2">
        {entry.description}
      </div>
      <div className="flex gap-2 mt-2 text-xs text-gray-500">
        <span>{entry.kind}</span>
        <span>·</span>
        <span>v{entry.version}</span>
        <span>·</span>
        <span>{entry.introduced_in}</span>
      </div>
    </button>
  );
}
