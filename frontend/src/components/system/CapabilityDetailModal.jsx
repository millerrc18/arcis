/**
 * Click-through detail view for a single capability.
 * v1 placeholder — commit 13 adds Mark Reviewed + full metadata rendering.
 */
export default function CapabilityDetailModal({ entry, onClose }) {
  if (!entry) return null;
  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-slate-800 rounded shadow-lg p-4 max-w-lg w-full"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-start mb-2">
          <h3 className="font-semibold">{entry.name}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-800">x</button>
        </div>
        <div className="text-xs text-gray-500 mb-2">
          {entry.kind} · {entry.category} · v{entry.version} · {entry.introduced_in}
        </div>
        <p className="text-sm text-gray-700 dark:text-gray-200">{entry.description}</p>
      </div>
    </div>
  );
}
