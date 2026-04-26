/**
 * TimeoutCell snapshot tests (Vitest + @testing-library/react).
 *
 * NOTE: Vitest and @testing-library/react are NOT currently in the project's
 * devDependencies. To run these tests:
 *   npm install --save-dev vitest @testing-library/react @testing-library/jest-dom jsdom
 * Then add to vite.config.js:
 *   test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test-setup.js'] }
 * And create src/test-setup.js:
 *   import '@testing-library/jest-dom'
 * Then run: npm test --prefix frontend -- --run TimeoutCell
 *
 * The tests below cover the 4 status values + LLM-mismatch warning icon.
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import TimeoutCell from './TimeoutCell'

describe('TimeoutCell', () => {
  it('renders on_track status with green color', () => {
    const { container } = render(
      <TimeoutCell durationDays={5} timeoutDays={15} status="on_track" progressPct={33.3} />
    )
    expect(container).toMatchSnapshot()
    const text = container.textContent
    expect(text).toContain('5')
    expect(text).toContain('15')
  })

  it('renders approaching status with amber color', () => {
    const { container } = render(
      <TimeoutCell durationDays={14} timeoutDays={15} status="approaching" progressPct={93.3} />
    )
    expect(container).toMatchSnapshot()
  })

  it('renders overdue status with red color', () => {
    const { container } = render(
      <TimeoutCell durationDays={20} timeoutDays={15} status="overdue" progressPct={100} />
    )
    expect(container).toMatchSnapshot()
  })

  it('renders unknown status with gray color when data is null', () => {
    const { container } = render(
      <TimeoutCell durationDays={null} timeoutDays={null} status="unknown" progressPct={null} />
    )
    expect(container).toMatchSnapshot()
    expect(container.textContent).toContain('--')
  })

  it('shows warning icon when llmTimeoutDays differs from timeoutDays', () => {
    const { container } = render(
      <TimeoutCell
        durationDays={8}
        timeoutDays={15}
        llmTimeoutDays={25}
        status="on_track"
        progressPct={53.3}
      />
    )
    expect(container).toMatchSnapshot()
    expect(container.textContent).toContain('⚠')
  })

  it('does NOT show warning icon when llmTimeoutDays matches timeoutDays', () => {
    const { container } = render(
      <TimeoutCell
        durationDays={5}
        timeoutDays={15}
        llmTimeoutDays={15}
        status="on_track"
        progressPct={33.3}
      />
    )
    expect(container.textContent).not.toContain('⚠')
  })

  it('shows "default" LLM caption when llmTimeoutDays is null', () => {
    const { container } = render(
      <TimeoutCell durationDays={5} timeoutDays={15} status="on_track" progressPct={33.3} />
    )
    expect(container.textContent).toContain('LLM: default')
  })
})
