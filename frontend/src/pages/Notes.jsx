import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Pin, PinOff, Search, Trash2 } from 'lucide-react'
import { api } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'

function noteToDraft(note) {
  return {
    title: note?.title || '',
    content: note?.content || '',
    tagsText: Array.isArray(note?.tags) ? note.tags.join(', ') : '',
    pinned: Boolean(note?.pinned),
  }
}

function normalizeTags(tagsText) {
  return tagsText
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean)
}

function serializeDraft(draft) {
  return JSON.stringify({
    title: draft?.title || '',
    content: draft?.content || '',
    tags: normalizeTags(draft?.tagsText || ''),
    pinned: Boolean(draft?.pinned),
  })
}

function previewText(content) {
  if (!content) return 'Blank note'
  return content.replace(/\s+/g, ' ').trim().slice(0, 120)
}

export default function Notes() {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['notes'],
    queryFn: api.fetchNotes,
    refetchInterval: 60000,
  })

  const notes = data?.notes || []
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState(null)
  const [draft, setDraft] = useState(null)
  const [lastSaved, setLastSaved] = useState(null)
  const [saveState, setSaveState] = useState('idle')

  const filteredNotes = useMemo(() => {
    const term = search.trim().toLowerCase()
    if (!term) return notes
    return notes.filter((note) => {
      const haystack = `${note.title} ${note.content} ${(note.tags || []).join(' ')}`.toLowerCase()
      return haystack.includes(term)
    })
  }, [notes, search])

  const selectedNote = notes.find((note) => note.note_id === selectedId) || null
  const hasUnsavedChanges = draft && lastSaved !== serializeDraft(draft)

  useEffect(() => {
    if (!selectedId && notes.length > 0) {
      setSelectedId(notes[0].note_id)
    }
    if (selectedId && !selectedNote && notes.length > 0) {
      setSelectedId(notes[0].note_id)
    }
    if (notes.length === 0) {
      setSelectedId(null)
      setDraft(null)
      setLastSaved(null)
    }
  }, [notes, selectedId, selectedNote])

  useEffect(() => {
    if (!selectedNote) return
    const nextDraft = noteToDraft(selectedNote)
    setDraft(nextDraft)
    setLastSaved(serializeDraft(nextDraft))
    setSaveState('idle')
  }, [selectedNote?.note_id, selectedNote?.updated_at])

  async function saveDraftSnapshot(noteId, draftSnapshot) {
    if (!noteId || !draftSnapshot) return
    const payload = {
      title: draftSnapshot.title || 'Untitled Note',
      content: draftSnapshot.content || '',
      tags: normalizeTags(draftSnapshot.tagsText || ''),
      pinned: Boolean(draftSnapshot.pinned),
    }
    const updated = await api.updateNote(noteId, payload)
    queryClient.setQueryData(['notes'], (current) => {
      const existing = current?.notes || []
      return {
        notes: existing.map((note) => (note.note_id === updated.note_id ? updated : note)),
      }
    })
    const normalized = noteToDraft(updated)
    setDraft(normalized)
    setLastSaved(serializeDraft(normalized))
    setSaveState('saved')
  }

  useEffect(() => {
    if (!selectedId || !draft || !hasUnsavedChanges) return undefined
    setSaveState('pending')
    const snapshot = { ...draft }
    const timer = window.setTimeout(async () => {
      setSaveState('saving')
      try {
        await saveDraftSnapshot(selectedId, snapshot)
      } catch {
        setSaveState('error')
      }
    }, 2000)
    return () => window.clearTimeout(timer)
  }, [selectedId, draft, hasUnsavedChanges])

  async function flushSave() {
    if (!selectedId || !draft || !hasUnsavedChanges) return
    setSaveState('saving')
    try {
      await saveDraftSnapshot(selectedId, draft)
    } catch {
      setSaveState('error')
    }
  }

  async function handleCreateNote() {
    const note = await api.createNote({
      title: 'Untitled Note',
      content: '',
      tags: [],
      pinned: false,
    })
    queryClient.setQueryData(['notes'], (current) => ({
      notes: [note, ...(current?.notes || [])],
    }))
    setSelectedId(note.note_id)
  }

  async function handleDeleteNote(noteId) {
    if (!noteId || !window.confirm('Delete this note?')) return
    await api.deleteNote(noteId)
    const remaining = notes.filter((note) => note.note_id !== noteId)
    queryClient.setQueryData(['notes'], { notes: remaining })
    setSelectedId(remaining[0]?.note_id || null)
  }

  if (isLoading) return <LoadingSpinner />

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-xl font-medium" style={{ color: 'var(--slate-100)' }}>Notes</h2>
          <p className="text-sm mt-1" style={{ color: 'var(--slate-400)' }}>
            Search, pin, and edit operating notes directly from the dashboard.
          </p>
        </div>
        <button
          onClick={handleCreateNote}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium"
          style={{ background: 'var(--teal-500)', color: 'white' }}
        >
          <Plus size={16} />
          New Note
        </button>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[320px,1fr] gap-4">
        <div className="rounded-lg p-4" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
          <div className="relative mb-4">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--slate-400)' }} />
            <input
              type="text"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search notes..."
              className="w-full pl-9 pr-3 py-2 rounded-lg text-sm"
              style={{ background: 'var(--slate-800)', border: '1px solid var(--slate-600)', color: 'var(--slate-100)' }}
            />
          </div>

          <div className="space-y-2 max-h-[65vh] overflow-y-auto">
            {filteredNotes.length === 0 ? (
              <div className="text-sm text-center py-8" style={{ color: 'var(--slate-400)' }}>
                {notes.length === 0 ? 'No notes yet.' : 'No notes match this search.'}
              </div>
            ) : (
              filteredNotes.map((note) => {
                const active = note.note_id === selectedId
                return (
                  <button
                    key={note.note_id}
                    onClick={() => setSelectedId(note.note_id)}
                    className="w-full text-left rounded-lg p-3 transition-colors"
                    style={{
                      background: active ? 'rgba(20, 184, 166, 0.12)' : 'var(--slate-800)',
                      border: `1px solid ${active ? 'rgba(20, 184, 166, 0.45)' : 'var(--slate-600)'}`,
                    }}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="font-medium text-sm" style={{ color: 'var(--slate-100)' }}>
                        {note.title}
                      </div>
                      {note.pinned && (
                        <Pin size={14} style={{ color: 'var(--amber-400)', flexShrink: 0 }} />
                      )}
                    </div>
                    <div className="text-xs mt-2" style={{ color: 'var(--slate-400)' }}>
                      {previewText(note.content)}
                    </div>
                    {(note.tags || []).length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-3">
                        {note.tags.map((tag) => (
                          <span
                            key={tag}
                            className="px-2 py-0.5 rounded-full text-xs"
                            style={{ background: 'rgba(148, 163, 184, 0.18)', color: 'var(--slate-300)' }}
                          >
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </button>
                )
              })
            )}
          </div>
        </div>

        <div className="rounded-lg p-4 md:p-5" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
          {!selectedNote || !draft ? (
            <div className="h-full min-h-[360px] flex items-center justify-center text-sm" style={{ color: 'var(--slate-400)' }}>
              Select a note or create a new one.
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <input
                  type="text"
                  value={draft.title}
                  onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}
                  onBlur={flushSave}
                  className="flex-1 min-w-[220px] text-lg font-medium bg-transparent border-b pb-2"
                  style={{ borderColor: 'var(--slate-600)', color: 'var(--slate-100)', outline: 'none' }}
                />
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setDraft((current) => ({ ...current, pinned: !current.pinned }))}
                    className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm"
                    style={{ background: 'var(--slate-800)', border: '1px solid var(--slate-600)', color: 'var(--slate-200)' }}
                  >
                    {draft.pinned ? <PinOff size={14} /> : <Pin size={14} />}
                    {draft.pinned ? 'Unpin' : 'Pin'}
                  </button>
                  <button
                    onClick={() => handleDeleteNote(selectedNote.note_id)}
                    className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm"
                    style={{ background: 'rgba(239, 68, 68, 0.12)', border: '1px solid rgba(239, 68, 68, 0.35)', color: '#fca5a5' }}
                  >
                    <Trash2 size={14} />
                    Delete
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-[1fr,160px] gap-3">
                <input
                  type="text"
                  value={draft.tagsText}
                  onChange={(event) => setDraft((current) => ({ ...current, tagsText: event.target.value }))}
                  onBlur={flushSave}
                  placeholder="tags, comma, separated"
                  className="w-full px-3 py-2 rounded-lg text-sm"
                  style={{ background: 'var(--slate-800)', border: '1px solid var(--slate-600)', color: 'var(--slate-100)' }}
                />
                <div className="px-3 py-2 rounded-lg text-sm flex items-center justify-center" style={{ background: 'var(--slate-800)', border: '1px solid var(--slate-600)', color: 'var(--slate-400)' }}>
                  {saveState === 'saving' && 'Saving...'}
                  {saveState === 'pending' && 'Autosave in 2s'}
                  {saveState === 'saved' && 'Saved'}
                  {saveState === 'error' && 'Save failed'}
                  {saveState === 'idle' && 'Ready'}
                </div>
              </div>

              <textarea
                value={draft.content}
                onChange={(event) => setDraft((current) => ({ ...current, content: event.target.value }))}
                onBlur={flushSave}
                placeholder="Write anything operational here..."
                className="w-full min-h-[420px] px-4 py-3 rounded-lg text-sm"
                style={{
                  background: 'var(--slate-900)',
                  border: '1px solid var(--slate-600)',
                  color: 'var(--slate-100)',
                  fontFamily: 'var(--font-mono)',
                  outline: 'none',
                }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
