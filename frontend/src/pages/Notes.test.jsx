/**
 * Notes.jsx — T17 TanStack v5 queryFn arrow-wrap tests
 *
 * Verifies that the useQuery call in Notes passes an arrow-function queryFn
 * (not a bare api.fetchNotes reference), so TanStack v5 does not receive
 * a QueryFunctionContext as the first arg to api.fetchNotes.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { api } from '../api'

vi.mock('@tanstack/react-query', () => ({
  useQuery: vi.fn(),
  useQueryClient: vi.fn(() => ({
    setQueryData: vi.fn(),
    invalidateQueries: vi.fn(),
  })),
}))

vi.mock('../config', () => ({
  IS_CLOUD: false,
  API_BASE: '',
  API_SECRET: '',
}))

vi.mock('../api', () => ({
  api: {
    fetchNotes: vi.fn(),
    createNote: vi.fn(),
    updateNote: vi.fn(),
    deleteNote: vi.fn(),
  },
}))

vi.mock('../components/LoadingSpinner', () => ({
  default: () => null,
}))

import { useQuery } from '@tanstack/react-query'
import Notes from './Notes'

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe('Notes — T17 queryFn arrow-wrap', () => {
  it('passes an arrow function as queryFn for notes query (not a bare api.fetchNotes ref)', () => {
    let notesQueryFn = null
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'notes') {
        notesQueryFn = opts.queryFn
      }
      return { data: { notes: [] }, isLoading: false, isPending: false, isError: false }
    })

    render(<Notes />)

    expect(notesQueryFn).not.toBeNull()
    expect(typeof notesQueryFn).toBe('function')
    expect(notesQueryFn).not.toBe(api.fetchNotes)
  })

  it('all useQuery queryFn values are functions, not bare api method refs', () => {
    const capturedOptions = []
    useQuery.mockImplementation((opts) => {
      capturedOptions.push(opts)
      return { data: { notes: [] }, isLoading: false, isPending: false, isError: false }
    })

    render(<Notes />)

    expect(capturedOptions.length).toBeGreaterThan(0)
    for (const opts of capturedOptions) {
      expect(typeof opts.queryFn).toBe('function')
      expect(opts.queryFn).not.toBe(api.fetchNotes)
    }
  })
})
