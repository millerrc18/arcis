import SystemIndexCard from "./SystemIndexCard";

/**
 * Group of capability cards sharing a category label, rendered as a
 * titled grid. Passed in already-filtered by the parent panel.
 */
export default function SystemIndexCategory({ category, entries, onOpenDetail }) {
  if (!entries || entries.length === 0) return null;
  return (
    <div className="mb-4">
      <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-2">
        {category} ({entries.length})
      </h4>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {entries.map((e) => (
          <SystemIndexCard key={`${e.kind}-${e.name}`} entry={e} onOpenDetail={onOpenDetail} />
        ))}
      </div>
    </div>
  );
}
