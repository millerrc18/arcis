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

  it('lead version matches src/version.py (currently v0.32.0)', () => {
    // When you cut a release, update this test to the new VERSION value
    // alongside src/version.py + CHANGELOG.md + WhatsNewPanel.jsx.
    // Per docs/versioning-policy.md, all four must move together.
    const { container } = render(<WhatsNewPanel />)
    const match = container.textContent.match(/v0\.\d+\.\d+/)
    expect(match).not.toBeNull()
    expect(match[0]).toBe('v0.32.0')
  })

  it('lead entry surfaces the most recent release date (2026-04-29)', () => {
    const { container } = render(<WhatsNewPanel />)
    expect(container.textContent).toContain('2026-04-29')
  })

  it('does NOT regress to a stale lead version', () => {
    // Locks the original Sprint 0 Wave 1a F-CHANGELOG regression class:
    // the panel had been advertising v0.25.0 (2026-04-18) as latest while
    // Track 1.5 + Round 8/10 + PR #690 had already shipped. Don't let
    // any old version slip back to the top.
    const { container } = render(<WhatsNewPanel />)
    const match = container.textContent.match(/v0\.\d+\.\d+/)
    expect(match).not.toBeNull()
    const stale = ['v0.25.0', 'v0.26.0', 'v0.27.0', 'v0.27.1', 'v0.28.0', 'v0.29.0', 'v0.30.0', 'v0.31.0']
    expect(stale).not.toContain(match[0])
  })

  it('lead entry references current sprint context (Sprint 1.C)', () => {
    const { container } = render(<WhatsNewPanel />)
    expect(container.textContent).toMatch(/Sprint 1\.C/)
  })

  it('renders the "What\'s New" heading + CHANGELOG.md footer', () => {
    const { container } = render(<WhatsNewPanel />)
    expect(container.textContent).toContain("What's New")
    expect(container.textContent).toContain('Full history in CHANGELOG.md')
  })
})
