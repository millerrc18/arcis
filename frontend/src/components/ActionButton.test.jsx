import { describe, it, expect, afterEach, vi, beforeEach } from 'vitest'
import { render, cleanup, fireEvent, act } from '@testing-library/react'
import ActionButton from './ActionButton.jsx'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('ActionButton — F1 cliOnly + secure-context fallback', () => {
  it('cliOnly=true: button has disabled attribute, opacity-50 class, and [CLI only] badge', () => {
    const { container } = render(
      <ActionButton
        cliOnly
        cliCommand="python -m src.main reconcile-live"
        whyDisabled="Requires local machine"
        onClick={() => {}}
      >
        Reconcile
      </ActionButton>,
    )
    const btn = container.querySelector('button')
    expect(btn).not.toBeNull()
    expect(btn.disabled).toBe(true)
    expect(btn.className).toMatch(/opacity-50/)
    expect(container.textContent).toContain('[CLI only]')
  })

  it('cliOnly=true: hover triggers tooltip containing cliCommand in monospace and Copy button', async () => {
    const { container } = render(
      <ActionButton
        cliOnly
        cliCommand="python -m src.main reconcile-live"
        whyDisabled="Requires local machine"
        onClick={() => {}}
      >
        Reconcile
      </ActionButton>,
    )
    const trigger = container.querySelector('span')
    fireEvent.mouseEnter(trigger)
    await new Promise((r) => setTimeout(r, 350))
    expect(document.body.textContent).toContain('python -m src.main reconcile-live')
    const allBtns = Array.from(document.body.querySelectorAll('button'))
    const copyButton = allBtns.find((b) => b.textContent === 'Copy')
    expect(copyButton).not.toBeNull()
  })

  it('Copy in secure context: navigator.clipboard.writeText called with cliCommand; Copied! shown', async () => {
    vi.stubGlobal('isSecureContext', true)
    const writeTextMock = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: writeTextMock },
      configurable: true,
      writable: true,
    })

    const { container } = render(
      <ActionButton
        cliOnly
        cliCommand="python -m src.main reconcile-live"
        whyDisabled="Requires local machine"
        onClick={() => {}}
      >
        Reconcile
      </ActionButton>,
    )
    const trigger = container.querySelector('span')
    fireEvent.mouseEnter(trigger)
    await new Promise((r) => setTimeout(r, 350))

    const allBtns = Array.from(document.body.querySelectorAll('button'))
    const copyBtn = allBtns.find((b) => b.textContent === 'Copy')
    expect(copyBtn).not.toBeNull()

    await act(async () => {
      fireEvent.click(copyBtn)
      await new Promise((r) => setTimeout(r, 50))
    })

    expect(writeTextMock).toHaveBeenCalledWith('python -m src.main reconcile-live')
    expect(document.body.textContent).toContain('Copied!')
  })

  it('Copy in non-secure context: Press Ctrl+C hint shown, no exception thrown', async () => {
    vi.stubGlobal('isSecureContext', false)
    Object.defineProperty(navigator, 'clipboard', {
      value: undefined,
      configurable: true,
      writable: true,
    })

    const { container } = render(
      <ActionButton
        cliOnly
        cliCommand="python -m src.main reconcile-live"
        whyDisabled="Requires local machine"
        onClick={() => {}}
      >
        Reconcile
      </ActionButton>,
    )
    const trigger = container.querySelector('span')
    fireEvent.mouseEnter(trigger)
    await new Promise((r) => setTimeout(r, 350))

    const allBtns = Array.from(document.body.querySelectorAll('button'))
    const copyBtn = allBtns.find((b) => b.textContent === 'Copy')
    expect(copyBtn).not.toBeNull()

    await act(async () => {
      fireEvent.click(copyBtn)
      await new Promise((r) => setTimeout(r, 50))
    })

    expect(document.body.textContent).toContain('Press Ctrl+C')
  })

  it('cliOnly=false + onClick: click fires onClick handler', () => {
    const onClickMock = vi.fn()
    const { container } = render(
      <ActionButton onClick={onClickMock}>
        Run
      </ActionButton>,
    )
    const btn = container.querySelector('button')
    expect(btn.disabled).toBe(false)
    fireEvent.click(btn)
    expect(onClickMock).toHaveBeenCalledTimes(1)
  })

  it('pending=true: button is disabled and spinner is rendered inline', () => {
    const { container } = render(
      <ActionButton pending onClick={() => {}}>
        Run
      </ActionButton>,
    )
    const btn = container.querySelector('button')
    expect(btn.disabled).toBe(true)
    const spinner =
      container.querySelector('[data-spinner]') ||
      container.querySelector('[role="status"]') ||
      container.querySelector('.animate-spin')
    expect(spinner).not.toBeNull()
  })
})
