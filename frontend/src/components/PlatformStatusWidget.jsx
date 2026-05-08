import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getPlatformStrategies } from "../api.js";

/**
 * Home-screen status card for the Research Platform. Renders only if
 * at least one strategy is registered (per Sprint 4 plan line 1028 /
 * Sprint 4 cont. non-negotiable gate — inert state shows nothing).
 */
export default function PlatformStatusWidget() {
  const { data: strategies = [], isLoading } = useQuery({
    queryKey: ["platform-strategies"],
    queryFn: () => getPlatformStrategies(),
  });

  if (isLoading) return null;
  if (!strategies || strategies.length === 0) return null;

  const counts = {
    proposed: 0,
    backtested: 0,
    shadow_trading: 0,
    production: 0,
    deprecated: 0,
  };
  for (const s of strategies) {
    counts[s.current_status] = (counts[s.current_status] || 0) + 1;
  }

  const awaitingReview = counts.backtested;

  const lastBacktestAt = strategies
    .map((s) => s.last_backtest_at)
    .filter(Boolean)
    .sort()
    .pop();

  return (
    <div className="arcis-card">
      <h3 className="text-sm font-semibold mb-2">Research Platform</h3>
      <div className="flex gap-2 flex-wrap mb-2">
        {Object.entries(counts).map(([status, n]) =>
          n > 0 ? (
            <span
              key={status}
              className={`px-2 py-0.5 text-xs rounded ${
                status === "shadow_trading"
                  ? "bg-yellow-100 text-yellow-800"
                  : status === "production"
                  ? "bg-green-100 text-green-800"
                  : status === "deprecated"
                  ? "bg-red-100 text-red-800"
                  : "bg-gray-100 text-gray-700"
              }`}
            >
              {n} {status.replace("_", " ")}
            </span>
          ) : null
        )}
      </div>
      {awaitingReview > 0 && (
        <div className="text-sm text-orange-700 mb-1">
          {awaitingReview} strateg{awaitingReview === 1 ? "y" : "ies"}{" "}
          ready for shadow approval &rarr;
        </div>
      )}
      {lastBacktestAt && (
        <div className="text-xs text-gray-500">
          Last backtest: {lastBacktestAt.slice(0, 19).replace("T", " ")}
        </div>
      )}
      <Link
        to="/research-platform"
        className="text-xs text-blue-600 hover:underline"
      >
        Open platform &rarr;
      </Link>
    </div>
  );
}
