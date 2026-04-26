/**
 * AuthGate regression tests (Vitest + @testing-library/react).
 *
 * Sprint-0 / F-AUTH (deferred from PR-690 review B2).
 *
 * The bug being locked: a conditional `return children` early-exit was placed
 * BEFORE a `useEffect` call inside the AuthGate function component, violating
 * React's Rules of Hooks. The fix moves `useEffect` ABOVE any early return so
 * the hook count is identical on every render path.
 *
 * Tests below cover both the BEHAVIOR (renders correctly under both
 * IS_CLOUD=true and IS_CLOUD=false) and the STRUCTURE (source-code ordering
 * of `useEffect` vs the IS_CLOUD early-return is asserted directly so any
 * future re-introduction of the anti-pattern fails CI).
 */
import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const AUTHGATE_PATH = resolve(__dirname, 'AuthGate.jsx')

afterEach(() => {
  cleanup()
  vi.resetModules()
  vi.unstubAllGlobals()
  // Wipe localStorage between tests so isSessionValid() starts fresh.
  if (typeof localStorage !== 'undefined') {
    localStorage.clear()
  }
})

describe('AuthGate — Rules of Hooks regression lock (F-AUTH)', () => {
  it('STRUCTURAL: useEffect appears BEFORE any conditional `return children` in AuthGate.jsx', () => {
    // This is the core regression lock. If anyone ever moves `useEffect` back
    // below the IS_CLOUD early return, this assertion fails — independent of
    // runtime behavior or environment flags.
    const source = readFileSync(AUTHGATE_PATH, 'utf8')

    const useEffectIdx = source.indexOf('useEffect(')
    expect(useEffectIdx).toBeGreaterThan(-1)

    // Match the dangerous early-return pattern: `if (!IS_CLOUD) return children`
    const earlyReturnRe = /if\s*\(\s*!\s*IS_CLOUD\s*\)\s*return\s+children/
    const earlyReturnMatch = source.match(earlyReturnRe)
    expect(earlyReturnMatch).not.toBeNull()
    const earlyReturnIdx = earlyReturnMatch.index

    expect(
      useEffectIdx,
      'useEffect must come before `if (!IS_CLOUD) return children` to satisfy Rules of Hooks',
    ).toBeLessThan(earlyReturnIdx)

    // Also lock the `if (authed) return children` order — that early return
    // must also come AFTER all hook calls.
    const authedReturnRe = /if\s*\(\s*authed\s*\)\s*return\s+children/
    const authedReturnMatch = source.match(authedReturnRe)
    expect(authedReturnMatch).not.toBeNull()
    expect(useEffectIdx).toBeLessThan(authedReturnMatch.index)
  })

  it('BEHAVIORAL: renders children directly when IS_CLOUD=false (local mode)', async () => {
    vi.resetModules()
    vi.doMock('../config', () => ({
      IS_CLOUD: false,
      API_BASE: '/api',
      API_SECRET: '',
    }))
    const { default: AuthGate } = await import('./AuthGate.jsx')

    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { getByTestId } = render(
      <AuthGate>
        <div data-testid="local-children">local mode children</div>
      </AuthGate>,
    )

    expect(getByTestId('local-children').textContent).toBe('local mode children')

    // No React hook-order or invariant error should have surfaced via console.error.
    const hookErrorCalls = errSpy.mock.calls.filter((args) =>
      args.some((a) => typeof a === 'string' && /Rendered (more|fewer) hooks|Rules of Hooks/i.test(a)),
    )
    expect(hookErrorCalls).toEqual([])
    errSpy.mockRestore()
  })

  it('BEHAVIORAL: renders sign-in form when IS_CLOUD=true and no session token exists', async () => {
    vi.resetModules()
    vi.doMock('../config', () => ({
      IS_CLOUD: true,
      API_BASE: '/api',
      API_SECRET: '',
    }))
    const { default: AuthGate } = await import('./AuthGate.jsx')

    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { container, queryByTestId } = render(
      <AuthGate>
        <div data-testid="cloud-children">should be hidden behind auth</div>
      </AuthGate>,
    )

    // Auth form is shown; protected children are NOT.
    expect(container.textContent).toContain('ARCIS')
    expect(container.querySelector('input[type="password"]')).not.toBeNull()
    expect(queryByTestId('cloud-children')).toBeNull()

    const hookErrorCalls = errSpy.mock.calls.filter((args) =>
      args.some((a) => typeof a === 'string' && /Rendered (more|fewer) hooks|Rules of Hooks/i.test(a)),
    )
    expect(hookErrorCalls).toEqual([])
    errSpy.mockRestore()
  })

  it('BEHAVIORAL: renders children directly when IS_CLOUD=true AND a valid session token exists', async () => {
    // Pre-seed a valid session so isSessionValid() returns true. The component
    // must register useEffect, then short-circuit via `if (authed) return children`
    // on the second render after setAuthed(true) fires.
    const TOKEN_KEY = 'hl_token'
    const TOKEN_TS_KEY = 'hl_token_ts'
    localStorage.setItem(TOKEN_KEY, 'abc123')
    localStorage.setItem(TOKEN_TS_KEY, String(Date.now()))

    vi.resetModules()
    vi.doMock('../config', () => ({
      IS_CLOUD: true,
      API_BASE: '/api',
      API_SECRET: '',
    }))
    const { default: AuthGate } = await import('./AuthGate.jsx')

    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { findByTestId } = render(
      <AuthGate>
        <div data-testid="cloud-authed-children">authed cloud content</div>
      </AuthGate>,
    )

    // After useEffect fires and setAuthed(true) flushes a re-render, the
    // protected children appear. If the hook-count changed between the two
    // renders, React would throw "Rendered more hooks than during the previous
    // render" — `findByTestId` (async, retries) would then fail.
    const protectedNode = await findByTestId('cloud-authed-children')
    expect(protectedNode.textContent).toBe('authed cloud content')

    const hookErrorCalls = errSpy.mock.calls.filter((args) =>
      args.some((a) => typeof a === 'string' && /Rendered (more|fewer) hooks|Rules of Hooks/i.test(a)),
    )
    expect(hookErrorCalls).toEqual([])
    errSpy.mockRestore()
  })
})
