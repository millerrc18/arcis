import { useMemo, useState } from "react";
import SystemIndexCategory from "./SystemIndexCategory";
import CapabilityDetailModal from "./CapabilityDetailModal";

/**
 * System Index panel — every registered capability, grouped by category,
 * with click-through to detail modal. Fed from /api/system/index.
 *
 * Search / filter UI is explicitly deferred to v1.1 per the sprint spec.
 * Categories are ordered by count (descending) so operators see the
 * busiest domains first.
 */
function groupByCategory(entries) {
  const groups = {};
  for (const e of entries) {
    const cat = e.category || "uncategorized";
    groups[cat] ||= [];
    groups[cat].push(e);
  }
  // Sort each group by name for deterministic order.
  for (const list of Object.values(groups)) {
    list.sort((a, b) => a.name.localeCompare(b.name));
  }
  return groups;
}

export default function SystemIndexPanel({ data, isLoading }) {
  const [selected, setSelected] = useState(null);

  const allEntries = useMemo(() => {
    if (!data) return [];
    return [
      ...(data.actions || []),
      ...(data.states || []),
      ...(data.systems || []),
      ...(data.decisions || []),
    ];
  }, [data]);

  const groups = useMemo(() => groupByCategory(allEntries), [allEntries]);
  const sortedCategories = useMemo(() => {
    return Object.keys(groups).sort((a, b) => groups[b].length - groups[a].length);
  }, [groups]);

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-slate-800 rounded shadow p-4 mb-4">
        <h3 className="text-sm font-semibold mb-2">System Index</h3>
        <div className="text-xs text-gray-500">Loading capabilities...</div>
      </div>
    );
  }

  if (allEntries.length === 0) {
    return (
      <div className="bg-white dark:bg-slate-800 rounded shadow p-4 mb-4">
        <h3 className="text-sm font-semibold mb-2">System Index</h3>
        <div className="text-xs text-gray-500">No capabilities registered yet.</div>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-800 rounded shadow p-4 mb-4">
      <div className="flex justify-between items-center mb-3">
        <h3 className="text-sm font-semibold">System Index</h3>
        <span className="text-xs text-gray-500">
          {allEntries.length} capabilities across {sortedCategories.length} categories
        </span>
      </div>
      {sortedCategories.map((cat) => (
        <SystemIndexCategory
          key={cat}
          category={cat}
          entries={groups[cat]}
          onOpenDetail={setSelected}
        />
      ))}
      <CapabilityDetailModal
        entry={selected}
        onClose={() => setSelected(null)}
      />
    </div>
  );
}
