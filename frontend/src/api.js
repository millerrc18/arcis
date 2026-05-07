import { API_BASE, API_SECRET, IS_CLOUD } from "./config";
import { clearAuthSession } from "./components/AuthGate";

const TOKEN_KEY = "hl_token";
const TOKEN_TS_KEY = "hl_token_ts";
const SESSION_MAX_MS = 24 * 60 * 60 * 1000; // 24 hours

function authHeaders() {
  const headers = { "Content-Type": "application/json" };
  // In cloud mode, use stored token; otherwise use static secret
  const token = localStorage.getItem(TOKEN_KEY) || API_SECRET;
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

function checkSessionTimeout() {
  if (!IS_CLOUD) return;
  const ts = localStorage.getItem(TOKEN_TS_KEY);
  if (ts && Date.now() - parseInt(ts, 10) > SESSION_MAX_MS) {
    clearAuthSession();
    window.location.reload();
  }
}

export async function fetchApi(path, options = {}) {
  checkSessionTimeout();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { ...authHeaders(), ...options.headers },
    ...options,
  });
  if (res.status === 401 && IS_CLOUD) {
    clearAuthSession();
    window.location.reload();
    throw new Error("Session expired");
  }
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  if (res.status === 204) return null;
  const text = await res.text();
  if (!text) return null;
  return JSON.parse(text);
}

export const api = {
  getStatus: () => fetchApi("/status"),
  getKpis: () => fetchApi("/kpis"),
  getConfig: () => fetchApi("/config"),
  updateConfig: (data) =>
    fetchApi("/config", { method: "PUT", body: JSON.stringify(data) }),
  triggerScan: () => fetchApi("/scan", { method: "POST" }),
  getLatestScan: () => fetchApi("/scan/latest"),
  getPackets: (params) => fetchApi(`/packets?${new URLSearchParams(params)}`),
  getPacket: (id) => fetchApi(`/packets/${id}`),
  getOpenTrades: (desk) =>
    fetchApi(`/shadow/open${desk ? `?desk=${encodeURIComponent(desk)}` : ""}`),
  getClosedTrades: (days = 30, desk) =>
    fetchApi(
      `/shadow/closed?days=${days}${desk ? `&desk=${encodeURIComponent(desk)}` : ""}`,
    ),
  getAccount: (desk) =>
    fetchApi(
      `/shadow/account${desk ? `?desk=${encodeURIComponent(desk)}` : ""}`,
    ),
  getMetrics: (days = 30, desk) =>
    fetchApi(
      `/shadow/metrics?days=${days}${desk ? `&desk=${encodeURIComponent(desk)}` : ""}`,
    ),
  getSharpeAttribution: (desk) =>
    fetchApi(
      `/shadow/sharpe-attribution${desk ? `?desk=${encodeURIComponent(desk)}` : ""}`,
    ),
  getShadowDesks: () => fetchApi("/shadow/desks"),
  closeTrade: (ticker) =>
    fetchApi(`/shadow/close/${ticker}`, { method: "POST" }),
  getTrainingStatus: () => fetchApi("/training/status"),
  getTrainingVersions: () => fetchApi("/training/versions"),
  getTrainingReport: () => fetchApi("/training/report"),
  getTrainingHistory: () => fetchApi("/training/history"),
  getDataCollectionStats: () => fetchApi("/data-collection-stats"),
  getScanMetrics: (limit = 20) => fetchApi(`/scan/metrics?limit=${limit}`),
  triggerBootstrap: (count) =>
    fetchApi("/training/bootstrap", {
      method: "POST",
      body: JSON.stringify({ count }),
    }),
  triggerTrain: () => fetchApi("/training/train", { method: "POST" }),
  triggerRollback: () => fetchApi("/training/rollback", { method: "POST" }),
  getPendingReviews: () => fetchApi("/review/pending"),
  getRecommendation: (id) => fetchApi(`/review/${id}`),
  submitReview: (id, data) =>
    fetchApi(`/review/${id}`, { method: "POST", body: JSON.stringify(data) }),
  markExecuted: (ticker) =>
    fetchApi(`/review/mark-executed/${ticker}`, { method: "POST" }),
  getScorecard: (weeks = 1) => fetchApi(`/review/scorecard?weeks=${weeks}`),
  getPostmortems: (params) =>
    fetchApi(`/review/postmortems?${new URLSearchParams(params)}`),
  getHaltStatus: () => fetchApi("/halt-status"),
  haltTrading: () => fetchApi("/halt-trading", { method: "POST" }),
  resumeTrading: () => fetchApi("/resume-trading", { method: "POST" }),
  getLatestAudit: () => fetchApi("/audit/latest"),
  getAuditHistory: (days = 7) => fetchApi(`/audit/history?days=${days}`),
  getCtoReport: (days = 7) => fetchApi(`/cto-report?days=${days}`),
  getDocsList: () => fetchApi("/docs"),
  getDoc: (docId) => fetchApi(`/docs/${docId}`),
  getMetricHistory: (days = 90) => fetchApi(`/metric-history?days=${days}`),
  getCosts: (days = 30) => fetchApi(`/costs?days=${days}`),
  getBuildScore: () => fetchApi("/build-score"),
  // Council
  getCouncilLatest: () => fetchApi("/council/latest"),
  getCouncilHistory: (days = 30) => fetchApi(`/council/history?days=${days}`),
  getCouncilSession: (id) => fetchApi(`/council/session/${id}`),
  askCouncilStrategic: (question) =>
    fetchApi("/council/strategic", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
  // Activity
  getActivityFeed: (limit = 50, eventType) =>
    fetchApi(
      `/activity/feed?limit=${limit}${eventType ? `&event_type=${eventType}` : ""}`,
    ),
  // Health Score
  getHealthScore: () => fetchApi("/health/score"),
  getHSHS: () => fetchApi("/health/hshs"),
  // Notes
  fetchNotes: () => fetchApi("/notes"),
  createNote: (data) =>
    fetchApi("/notes", { method: "POST", body: JSON.stringify(data) }),
  updateNote: (noteId, data) =>
    fetchApi(`/notes/${noteId}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteNote: (noteId) => fetchApi(`/notes/${noteId}`, { method: "DELETE" }),
  // Live Trading
  getLiveTrades: () => fetchApi("/live/trades"),
  getLiveSummary: () => fetchApi("/live/summary"),
  // Settings
  getSettings: () => fetchApi("/settings"),
  updateSettings: (data) =>
    fetchApi("/settings", { method: "POST", body: JSON.stringify(data) }),
  clearOverrides: () => fetchApi("/settings/overrides", { method: "DELETE" }),
  // Actions (via command queue)
  triggerActionScan: () => fetchApi("/actions/scan", { method: "POST" }),
  triggerCtoReport: () => fetchApi("/actions/cto-report", { method: "POST" }),
  triggerCollectTraining: () =>
    fetchApi("/actions/collect-training", { method: "POST" }),
  triggerTrainPipeline: () =>
    fetchApi("/actions/train-pipeline", { method: "POST" }),
  triggerScore: () => fetchApi("/actions/score", { method: "POST" }),
  triggerCouncil: () => fetchApi("/actions/council", { method: "POST" }),
  triggerCollectData: () =>
    fetchApi("/actions/collect-data", { method: "POST" }),
  // Command queue
  submitCommand: (data) =>
    fetchApi("/commands/submit", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  getCommandStatus: (id) => fetchApi(`/commands/${id}/status`),
  getRecentCommands: (limit = 20) =>
    fetchApi(`/commands/recent?limit=${limit}`),
  // Expire stale pending commands (optional — may be a no-op in pure-local setups)
  clearStaleCommands: () =>
    fetchApi("/commands/expire-stale", { method: "POST" }),
  // Logs
  getRecentLogs: (params = {}) =>
    fetchApi(`/logs/recent?${new URLSearchParams(params)}`),
  // Projections
  getProjectionsLive: () => fetchApi("/projections/live"),
  // System Validation
  getValidation: () => fetchApi("/system/validation"),
  runValidation: () => fetchApi("/system/validation?fresh=true"),
  // DB Schema
  getTableCounts: () => fetchApi("/system/table-counts"),
  // Attribution
  getAttributionStats: () => fetchApi("/attribution/stats"),
  // Stress Testing
  getStressTestResults: () => fetchApi("/stress-test/results"),
  // Simulation
  getSimulationResults: () => fetchApi("/simulation/results"),
  // Model Performance
  getModelPerformance: () => fetchApi("/model-performance"),
  // Monitoring
  getMonitoringSnapshot: () => fetchApi("/monitoring/snapshot"),
  getMonitoringHistory: (hours = 24) =>
    fetchApi(`/monitoring/history?hours=${hours}`),
  // Strategy
  getStrategyDetail: (strategy) => fetchApi(`/strategy-detail/${strategy}`),
  // IB Shadow
  getIBShadowSummary: () => fetchApi("/ib-shadow/summary"),
  getIBShadowLog: (limit = 50) => fetchApi(`/ib-shadow/log?limit=${limit}`),
  getIBShadowHealth: () => fetchApi("/ib-shadow/health"),
  // IB Gateway Status
  getIBStatus: () => fetchApi("/ib/status"),
  // Diagnostic runs
  triggerRegimeDiagnostic: (opts = {}) =>
    fetchApi("/diagnostic-runs/regime", {
      method: "POST",
      body: JSON.stringify(opts),
    }),
  triggerForensicAudit: () =>
    fetchApi("/diagnostic-runs/forensic", {
      method: "POST",
      body: JSON.stringify({}),
    }),
  // training-data v1-citation audit
  triggerTrainingAudit: (opts = {}) =>
    fetchApi("/diagnostic-runs/training-audit", {
      method: "POST",
      body: JSON.stringify(opts),
    }),
  getDiagnosticRuns: (params = {}) => {
    const q = new URLSearchParams(params).toString();
    return fetchApi(`/diagnostic-runs${q ? `?${q}` : ""}`);
  },
  getDiagnosticRun: (runId) => fetchApi(`/diagnostic-runs/${runId}`),
  getDiagnosticRunReport: (runId) =>
    fetchApi(`/diagnostic-runs/${runId}/report`),
  getDiagnosticRunPlots: (runId) => fetchApi(`/diagnostic-runs/${runId}/plots`),
  // Capability Registry
  getSystemIndex: () => fetchApi("/system/index"),
  markReviewed: (name) =>
    fetchApi(`/system/index/${encodeURIComponent(name)}/mark-reviewed`, {
      method: "POST",
    }),
};

// Platform / Strategy Research helpers (Task 12a)
export async function getPlatformStrategies() {
  return fetchApi("/platform/strategies");
}

export async function getPlatformStrategyDetail(id) {
  return fetchApi(`/platform/strategies/${encodeURIComponent(id)}`);
}

export async function getPlatformBacktestResults(strategy_id, limit = 20) {
  const qs = new URLSearchParams({ strategy_id, limit: String(limit) });
  return fetchApi(`/platform/backtest-results?${qs}`);
}

export async function getPlatformBacktestTrades(result_id) {
  const qs = new URLSearchParams({ result_id });
  return fetchApi(`/platform/backtest-trades?${qs}`);
}

export async function getPlatformPromotionEvents(strategy_id, limit = 50) {
  const qs = new URLSearchParams({ strategy_id, limit: String(limit) });
  return fetchApi(`/platform/promotion-events?${qs}`);
}

// Walk-forward validation v1 helpers (three-state outcome dashboard)
export async function getWalkforwardRuns(params = {}) {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== "") qs.append(k, String(v));
  });
  const suffix = qs.toString() ? `?${qs}` : "";
  return fetchApi(`/walkforward/runs${suffix}`);
}

export async function getWalkforwardRun(runId) {
  return fetchApi(`/walkforward/runs/${encodeURIComponent(runId)}`);
}

export async function getWalkforwardRunWindows(runId) {
  return fetchApi(`/walkforward/runs/${encodeURIComponent(runId)}/windows`);
}

export async function getWalkforwardRunTrades(runId, windowIndex = null) {
  const qs = new URLSearchParams();
  if (windowIndex !== null && windowIndex !== undefined) {
    qs.append("window_index", String(windowIndex));
  }
  const suffix = qs.toString() ? `?${qs}` : "";
  return fetchApi(
    `/walkforward/runs/${encodeURIComponent(runId)}/trades${suffix}`,
  );
}
