import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";

/**
 * Click-through detail view for a single capability. Renders all
 * metadata + live state + Mark Reviewed button. The Mark Reviewed
 * click persists last_reviewed_date_override to operator_view_state
 * and invalidates the system-index query so the card's review pill
 * clears immediately.
 */

function Row({ label, children }) {
  return (
    <div className="grid grid-cols-[120px_1fr] gap-2 py-1 text-sm">
      <div className="text-gray-500 dark:text-gray-400">{label}</div>
      <div className="text-gray-800 dark:text-gray-200 break-words">{children}</div>
    </div>
  );
}

function SchemaBox({ title, schema }) {
  if (!schema) return null;
  return (
    <div className="mt-2">
      <div className="text-xs text-gray-500 mb-1">{title}</div>
      <pre className="text-xs bg-gray-50 dark:bg-slate-900 p-2 rounded overflow-x-auto">
        {JSON.stringify(schema, null, 2)}
      </pre>
    </div>
  );
}

function formatLive(entry) {
  if (entry.kind === "action" || entry.kind === "decision") return null;
  const live = entry.kind === "state" ? entry.live : entry.health;
  if (!live) return null;
  if (live.status !== "ok") {
    return (
      <div className="text-xs text-gray-500">
        status: {live.status}
        {live.error ? ` — ${live.error}` : ""}
      </div>
    );
  }
  const value = live.result;
  return (
    <pre className="text-xs bg-gray-50 dark:bg-slate-900 p-2 rounded overflow-x-auto">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export default function CapabilityDetailModal({ entry, onClose }) {
  const qc = useQueryClient();
  const [markStatus, setMarkStatus] = useState(null);

  const markMutation = useMutation({
    mutationFn: () => api.markReviewed(entry.name),
    onSuccess: () => {
      setMarkStatus("ok");
      qc.invalidateQueries({ queryKey: ["system-index"] });
    },
    onError: (err) => {
      setMarkStatus(`error: ${err.message || "unknown"}`);
    },
  });

  if (!entry) return null;
  const effectiveReviewed = entry.last_reviewed_date_override || entry.last_reviewed_date;

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-slate-800 rounded shadow-lg p-5 max-w-2xl w-full max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-start mb-3">
          <div>
            <h3 className="font-semibold text-lg">{entry.name}</h3>
            <div className="text-xs text-gray-500">
              {entry.kind} · {entry.category} · v{entry.version} · {entry.introduced_in}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-800 text-xl leading-none"
            aria-label="Close"
          >
            x
          </button>
        </div>

        <p className="text-sm text-gray-700 dark:text-gray-200 mb-3">{entry.description}</p>

        <Row label="Maintainer">{entry.maintainer}</Row>
        <Row label="Last reviewed">{effectiveReviewed}</Row>
        {entry.deprecated && (
          <Row label="Deprecated">
            replaced by <code className="text-red-700">{entry.deprecated_replacement}</code>
          </Row>
        )}

        {entry.kind === "action" && (
          <>
            <Row label="Kickoff">
              <code className="text-xs">{entry.kickoff_endpoint}</code>
              {!entry.ui_kickoff_available && (
                <span className="text-xs text-gray-500 ml-2">(CLI-only)</span>
              )}
            </Row>
            <Row label="Duration">{entry.estimated_duration}</Row>
            <SchemaBox title="input_schema" schema={entry.input_schema} />
            <SchemaBox title="output_schema" schema={entry.output_schema} />
          </>
        )}

        {entry.kind === "state" && (
          <>
            <Row label="Refresh">{entry.refresh_hint}</Row>
            <Row label="Current value">{formatLive(entry)}</Row>
          </>
        )}

        {entry.kind === "system" && (
          <>
            <Row label="Expected runtime">{entry.expected_runtime}</Row>
            <Row label="Current health">{formatLive(entry)}</Row>
          </>
        )}

        {entry.kind === "decision" && (
          <>
            <Row label="Decision">{entry.decision_text}</Row>
            <Row label="Rationale">{entry.rationale}</Row>
            <Row label="Revisit when">{entry.revisit_trigger}</Row>
          </>
        )}

        <div className="mt-4 pt-3 border-t border-gray-200 dark:border-slate-700 flex items-center gap-2">
          <button
            onClick={() => markMutation.mutate()}
            disabled={markMutation.isPending}
            className="px-3 py-1.5 text-xs rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {markMutation.isPending ? "Saving..." : "Mark Reviewed"}
          </button>
          {markStatus === "ok" && (
            <span className="text-xs text-green-700">Reviewed today.</span>
          )}
          {markStatus && markStatus !== "ok" && (
            <span className="text-xs text-red-700">{markStatus}</span>
          )}
        </div>
      </div>
    </div>
  );
}
