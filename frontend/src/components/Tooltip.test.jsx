import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, cleanup, fireEvent, act } from '@testing-library/react'
import Tooltip from './Tooltip.jsx'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('Tooltip — interactive prop', () => {
  it('default (interactive not set): tooltip surface has pointerEvents none', async () => {
    const { container } = render(
      <Tooltip content="hello">
        <span>hover me</span>
      </Tooltip>,
    )
    const trigger = container.querySelector('span[style]')
    fireEvent.mouseEnter(trigger)
    await new Promise((r) => setTimeout(r, 350))
    const surface = document.body.querySelector('[data-tooltip-surface]')
    expect(surface).not.toBeNull()
    expect(surface.style.pointerEvents).toBe('none')
  })

  it('interactive=false: tooltip surface has pointerEvents none', async () => {
    const { container } = render(
      <Tooltip content="hello" interactive={false}>
        <span>hover me</span>
      </Tooltip>,
    )
    const trigger = container.querySelector('span[style]')
    fireEvent.mouseEnter(trigger)
    await new Promise((r) => setTimeout(r, 350))
    const surface = document.body.querySelector('[data-tooltip-surface]')
    expect(surface).not.toBeNull()
    expect(surface.style.pointerEvents).toBe('none')
  })

  it('interactive=true: tooltip surface has pointerEvents auto', async () => {
    const { container } = render(
      <Tooltip content="hello" interactive={true}>
        <span>hover me</span>
      </Tooltip>,
    )
    const trigger = container.querySelector('span[style]')
    fireEvent.mouseEnter(trigger)
    await new Promise((r) => setTimeout(r, 350))
    const surface = document.body.querySelector('[data-tooltip-surface]')
    expect(surface).not.toBeNull()
    expect(surface.style.pointerEvents).toBe('auto')
  })

  it('interactive=true: moving mouse from trigger onto tooltip surface does NOT hide tooltip', async () => {
    const { container } = render(
      <Tooltip content="hello" interactive={true} delay={100}>
        <span>hover me</span>
      </Tooltip>,
    )
    const trigger = container.querySelector('span[style]')
    fireEvent.mouseEnter(trigger)
    await new Promise((r) => setTimeout(r, 150))
    expect(document.body.querySelector('[data-tooltip-surface]')).not.toBeNull()

    fireEvent.mouseLeave(trigger)
    const surface = document.body.querySelector('[data-tooltip-surface]')
    expect(surface).not.toBeNull()
    fireEvent.mouseEnter(surface)
    await new Promise((r) => setTimeout(r, 100))
    expect(document.body.querySelector('[data-tooltip-surface]')).not.toBeNull()
  })

  it('interactive=true: moving mouse off tooltip surface hides it after delay', async () => {
    const { container } = render(
      <Tooltip content="hello" interactive={true} delay={50}>
        <span>hover me</span>
      </Tooltip>,
    )
    const trigger = container.querySelector('span[style]')
    fireEvent.mouseEnter(trigger)
    await new Promise((r) => setTimeout(r, 100))
    expect(document.body.querySelector('[data-tooltip-surface]')).not.toBeNull()

    fireEvent.mouseLeave(trigger)
    const surface = document.body.querySelector('[data-tooltip-surface]')
    fireEvent.mouseEnter(surface)
    fireEvent.mouseLeave(surface)
    await new Promise((r) => setTimeout(r, 400))
    expect(document.body.querySelector('[data-tooltip-surface]')).toBeNull()
  })

  it('interactive=false (default): mouseLeave trigger immediately hides tooltip (no hover-bridge)', async () => {
    const { container } = render(
      <Tooltip content="hello" delay={50}>
        <span>hover me</span>
      </Tooltip>,
    )
    const trigger = container.querySelector('span[style]')
    fireEvent.mouseEnter(trigger)
    await new Promise((r) => setTimeout(r, 100))
    expect(document.body.querySelector('[data-tooltip-surface]')).not.toBeNull()

    fireEvent.mouseLeave(trigger)
    await new Promise((r) => setTimeout(r, 50))
    expect(document.body.querySelector('[data-tooltip-surface]')).toBeNull()
  })
})
