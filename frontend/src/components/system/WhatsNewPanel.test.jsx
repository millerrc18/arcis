/**
 * Regression-locking test for WhatsNewPanel.
 * Sprint 0 Wave 1a / F-CHANGELOG (PR #690 review B3 deferred-to-Sprint-0):
 *   the panel was still advertising v0.25.0 (2026-04-18) as the latest
 *   release after Track 1.5 + Round 8/10 + PR #690 had all shipped,
 *   making the operator's Monday cockpit show months-old "current" content.
 *
 * Locks the regression class — if someone refreshes RECENT_ENTRIES
 * without bringing the most-recent entry forward, this fails.
 *
 * Pair this test with bumps to:
 *   - frontend/src/components/system/WhatsNewPanel.jsx (RECENT_ENTRIES)
 *   - CHANGELOG.md (top-of-file entry)
 *   - src/version.py (VERSION constant)
 * All three must stay in sync.
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import WhatsNewPanel from './WhatsNewPanel'

describe('WhatsNewPanel regression — current release surfaced', () => {
  it('renders without crashing', () => {
    const { container } = render(<WhatsNewPanel />)
    expect(container.firstChild).not.toBeNull()
  })

  it('most recent version listed is v0.27.1, not the stale v0.25.0', () => {
    const { container } = render(<WhatsNewPanel />)
    // Pull all version strings in render order. The first one must be the
    // current release, not the months-old entry the operator complained about.
    const text = container.textContent
    const firstV0271 = text.indexOf('v0.27.1')
    const firstV025 = text.indexOf('v0.25.0')
    expect(firstV0271).toBeGreaterThanOrEqual(0)
    // If v0.25.0 is rendered at all, it must come AFTER v0.27.1 (i.e. it
    // is a historical reference, not the lead). Strict: the lead version
    // is v0.27.1 and it must appear before any v0.25.0 (regardless of
    // whether v0.25.0 is in the trim window or not).
    if (firstV025 >= 0) {
      expect(firstV0271).toBeLessThan(firstV025)
    }
  })

  it('renders today\'s release date 2026-04-26', () => {
    const { container } = render(<WhatsNewPanel />)
    expect(container.textContent).toContain('2026-04-26')
  })

  it('does NOT show v0.25.0 as the lead entry (the regression we are locking)', () => {
    const { container } = render(<WhatsNewPanel />)
    // The very first version label rendered must NOT be v0.25.0.
    // Find the first version-prefixed token.
    const match = container.textContent.match(/v0\.\d+\.\d+/)
    expect(match).not.toBeNull()
    expect(match[0]).not.toBe('v0.25.0')
  })

  it('mentions PR #690 in the lead entry (anchor for Sprint 0 Wave 1a)', () => {
    const { container } = render(<WhatsNewPanel />)
    expect(container.textContent).toMatch(/PR #690/)
  })

  it('renders the "What\'s New" heading + CHANGELOG.md footer', () => {
    const { container } = render(<WhatsNewPanel />)
    expect(container.textContent).toContain("What's New")
    expect(container.textContent).toContain('Full history in CHANGELOG.md')
  })
})
