/**
 * Format an ISO 8601 timestamp to the user's local timezone.
 *
 * @param {string} isoString - ISO date string (e.g., "2024-03-15T14:30:00Z")
 * @param {object} [options] - Intl.DateTimeFormat options override
 * @returns {string} Formatted local date/time string, or '--' if invalid
 */
export function formatTimestamp(isoString, options = {}) {
  if (!isoString) return '--'
  try {
    const date = new Date(isoString)
    if (isNaN(date.getTime())) return '--'
    const defaults = {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      ...options,
    }
    return new Intl.DateTimeFormat(undefined, defaults).format(date)
  } catch {
    return '--'
  }
}

/**
 * Format an ISO 8601 timestamp to date-only in the user's local timezone.
 *
 * @param {string} isoString - ISO date string
 * @returns {string} Formatted local date string, or '--' if invalid
 */
export function formatDate(isoString) {
  return formatTimestamp(isoString, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: undefined,
    minute: undefined,
  })
}

/**
 * Format an ISO 8601 timestamp to relative time (e.g., "5m ago", "2h ago").
 *
 * @param {string} isoString - ISO date string
 * @returns {string} Relative time string, or '--' if invalid
 */
export function formatRelativeTime(isoString) {
  if (!isoString) return '--'
  try {
    const date = new Date(isoString)
    if (isNaN(date.getTime())) return '--'
    const ms = Date.now() - date.getTime()
    const mins = Math.floor(ms / 60000)
    if (mins < 1) return 'Just now'
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    const days = Math.floor(hrs / 24)
    if (days === 1) return 'Yesterday'
    if (days < 30) return `${days}d ago`
    return formatDate(isoString)
  } catch {
    return '--'
  }
}
