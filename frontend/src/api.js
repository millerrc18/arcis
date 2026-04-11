import { API_BASE, API_SECRET, IS_CLOUD } from './config'
import { clearAuthSession } from './components/AuthGate'

const TOKEN_KEY = 'hl_token'
const TOKEN_TS_KEY = 'hl_token_ts'
const SESSION_MAX_MS = 24 * 60 * 60 * 1000 // 24 hours

function authHeaders() {
  const headers = { 'Content-Type': 'application/json' }
  // In cloud mode, use stored token; otherwise use static secret
  const token = localStorage.getItem(TOKEN_KEY) || API_SECRET
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return headers
}

function checkSessionTimeout() {
  if (!IS_CLOUD) return
  const ts = localStorage.getItem(TOKEN_TS_KEY)
  if (ts && Date.now() - parseInt(ts, 10) > SESSION_MAX_MS) {
    clearAuthSession()
    window.location.reload()
  }
}

export async function fetchApi(path, options = {}) {
  checkSessionTimeout()
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { ...authHeaders(), ...options.headers },
    ...options,
  })
  if (res.status === 401 && IS_CLOUD) {
    clearAuthSession()
    window.location.reload()
    throw new Error('Session expired')
  }
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  if (res.status === 204) return null
  const text = await res.text()
  if (!text) return null
  return JSON.parse(text)
}

export const api = {
  getStatus: () => fetchApi('/status'),
  getConfig: () => fetchApi('/config'),
  updateConfig: (data) => fetchApi('/config', { method: 'PUT', body: JSON.stringify(data) }),
  triggerScan: () => fetchApi('/scan', { method: 'POST' }),
  getLatestScan: () => fetchApi('/scan/latest'),
  getPackets: (params) => fetchApi(`/packets?${new URLSearchParams(params)}`),
  getPacket: (id) => fetchApi(`/packets/${id}`),
  getOpenTrades: () => fetchApi('/shadow/open'),
  getClosedTrades: (days = 30) => fetchApi(`/shadow/closed?days=${days}`),
  getAccount: () => fetchApi('/shadow/account'),
  getMetrics: (days = 30) => fetchApi(`/shadow/metrics?days=${days}`),
  closeTrade: (ticker) => fetchApi(`/shadow/close/${ticker}`, { method: 'POST' }),
  getTrainingStatus: () => fetchApi('/training/status'),
  getTrainingVersions: () => fetchApi('/training/versions'),
  getTrainingReport: () => fetchApi('/training/report'),
  getTrainingHistory: () => fetchApi('/training/history'),
  getDataCollectionStats: () => fetchApi('/data-collection-stats'),
  getScanMetrics: (limit = 20) => fetchApi(`/scan/metrics?limit=${limit}`),
  triggerBootstrap: (count) => fetchApi('/training/bootstrap', { method: 'POST', body: JSON.stringify({ count }) }),
  triggerTrain: () => fetchApi('/training/train', { method: 'POST' }),
  triggerRollback: () => fetchApi('/training/rollback', { method: 'POST' }),
  getPendingReviews: () => fetchApi('/review/pending'),
  getRecommendation: (id) => fetchApi(`/review/${id}`),
  submitReview: (id, data) => fetchApi(`/review/${id}`, { method: 'POST', body: JSON.stringify(data) }),
  markExecuted: (ticker) => fetchApi(`/review/mark-executed/${ticker}`, { method: 'POST' }),
  getScorecard: (weeks = 1) => fetchApi(`/review/scorecard?weeks=${weeks}`),
  getPostmortems: (params) => fetchApi(`/review/postmortems?${new URLSearchParams(params)}`),
  getHaltStatus: () => fetchApi('/halt-status'),
  haltTrading: () => fetchApi('/halt-trading', { method: 'POST' }),
  resumeTrading: () => fetchApi('/resume-trading', { method: 'POST' }),
  getLatestAudit: () => fetchApi('/audit/latest'),
  getAuditHistory: (days = 7) => fetchApi(`/audit/history?days=${days}`),
  getCtoReport: (days = 7) => fetchApi(`/cto-report?days=${days}`),
  getDocsList: () => fetchApi('/docs'),
  getDoc: (docId) => fetchApi(`/docs/${docId}`),
  getMetricHistory: (days = 90) => fetchApi(`/metric-history?days=${days}`),
  getCosts: (days = 30) => fetchApi(`/costs?days=${days}`),
  getBuildScore: () => fetchApi('/build-score'),
  // Council
  getCouncilLatest: () => fetchApi('/council/latest'),
  getCouncilHistory: (days = 30) => fetchApi(`/council/history?days=${days}`),
  getCouncilSession: (id) => fetchApi(`/council/session/${id}`),
  askCouncilStrategic: (question) => fetchApi('/council/strategic', { method: 'POST', body: JSON.stringify({ question }) }),
  // Activity
  getActivityFeed: (limit = 50, eventType) => fetchApi(`/activity/feed?limit=${limit}${eventType ? `&event_type=${eventType}` : ''}`),
  // Health Score
  getHealthScore: () => fetchApi('/health/score'),
  getHSHS: () => fetchApi('/health/hshs'),
  // Notes
  fetchNotes: () => fetchApi('/notes'),
  createNote: (data) => fetchApi('/notes', { method: 'POST', body: JSON.stringify(data) }),
  updateNote: (noteId, data) => fetchApi(`/notes/${noteId}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteNote: (noteId) => fetchApi(`/notes/${noteId}`, { method: 'DELETE' }),
  // Live Trading
  getLiveTrades: () => fetchApi('/live/trades'),
  getLiveSummary: () => fetchApi('/live/summary'),
  // Settings
  getSettings: () => fetchApi('/settings'),
  updateSettings: (data) => fetchApi('/settings', { method: 'POST', body: JSON.stringify(data) }),
  clearOverrides: () => fetchApi('/settings/overrides', { method: 'DELETE' }),
  // Actions (via command queue)
  triggerActionScan: () => fetchApi('/actions/scan', { method: 'POST' }),
  triggerCtoReport: () => fetchApi('/actions/cto-report', { method: 'POST' }),
  triggerCollectTraining: () => fetchApi('/actions/collect-training', { method: 'POST' }),
  triggerTrainPipeline: () => fetchApi('/actions/train-pipeline', { method: 'POST' }),
  triggerScore: () => fetchApi('/actions/score', { method: 'POST' }),
  triggerCouncil: () => fetchApi('/actions/council', { method: 'POST' }),
  triggerCollectData: () => fetchApi('/actions/collect-data', { method: 'POST' }),
  // Command queue
  submitCommand: (data) => fetchApi('/commands/submit', { method: 'POST', body: JSON.stringify(data) }),
  getCommandStatus: (id) => fetchApi(`/commands/${id}/status`),
  getRecentCommands: (limit = 20) => fetchApi(`/commands/recent?limit=${limit}`),
  // Logs
  getRecentLogs: (params = {}) => fetchApi(`/logs/recent?${new URLSearchParams(params)}`),
  // Projections
  getProjectionsLive: () => fetchApi('/projections/live'),
  // System Validation
  getValidation: () => fetchApi('/system/validation'),
  runValidation: () => fetchApi('/system/validation?fresh=true'),
  // DB Schema
  getTableCounts: () => fetchApi('/system/table-counts'),
  // Attribution
  getAttributionStats: () => fetchApi('/attribution/stats'),
  // Stress Testing
  getStressTestResults: () => fetchApi('/stress-test/results'),
  // Simulation
  getSimulationResults: () => fetchApi('/simulation/results'),
  // Model Performance
  getModelPerformance: () => fetchApi('/model-performance'),
  // Monitoring
  getMonitoringSnapshot: () => fetchApi('/monitoring/snapshot'),
  getMonitoringHistory: (hours = 24) => fetchApi(`/api/monitoring/history?hours=${hours}`),
  // Strategy
  getStrategyDetail: (strategy) => fetchApi(`/api/strategy-detail/${strategy}`),
  // IB Shadow
  getIBShadowSummary: () => fetchApi('/ib-shadow/summary'),
  getIBShadowLog: (limit = 50) => fetchApi(`/ib-shadow/log?limit=${limit}`),
  getIBShadowHealth: () => fetchApi('/ib-shadow/health'),
}
