import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Pin, PinOff, Search, Trash2, StickyNote } from 'lucide-react'
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
  // Truncate to ~3 lines worth of text
  const text = content.replace(/\s+/g, ' ').trim()
  return text.length > 120 ? text.slice(0, 120) + '...' : text
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now - d
  if (diff < 60000) return 'just now'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
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
  const [tagFilter, setTagFilter] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [draft, setDraft] = useState(null)
  const [lastSaved, setLastSaved] = useState(null)
  const [saveState, setSaveState] = useState('idle')

  // Collect all unique tags
  const allTags = useMemo(() => {
    const tags = new Set()
    for (const note of notes) {
      for (const tag of (note.tags || [])) tags.add(tag)
    }
    return [...tags].sort()
  }, [notes])

  const filteredNotes = useMemo(() => {
    let result = notes
    const term = search.trim().toLowerCase()
    if (term) {
      result = result.filter((note) => {
        const haystack = `${note.title} ${note.content} ${(note.tags || []).join(' ')}`.toLowerCase()
        return haystack.includes(term)
      })
    }
    if (tagFilter) {
      result = result.filter((note) => (note.tags || []).includes(tagFilter))
    }
    // Sort: pinned first, then reverse chronological
    return [...result].sort((a, b) => {
      if (a.pinned && !b.pinned) return -1
      if (!a.pinned && b.pinned) return 1
      return new Date(b.updated_at || b.created_at || 0) - new Date(a.updated_at || a.created_at || 0)
    })
  }, [notes, search, tagFilter])

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
    if (!noteId || !window.confirm('Delete this note? This action cannot be undone.')) return
    await api.deleteNote(noteId)
    const remaining = notes.filter((note) => note.note_id !== noteId)
    queryClient.setQueryData(['notes'], { notes: remaining })
    setSelectedId(remaining[0]?.note_id || null)
  }

  if (isLoading) return <LoadingSpinner />

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h2 className="text-xl font-medium uppercase" style={{ color: 'var(--arcis-text-primary)', letterSpacing: '0.06em' }}>Notes</h2>
        <button
          onClick={handleCreateNote}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium uppercase"
          style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-accent)', color: 'white', letterSpacing: '0.06em' }}
        >
          <Plus size={16} />
          New Note
        </button>
      </div>

      {/* Tag filter pills */}
      {allTags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => setTagFilter(null)}
            className="px-2.5 py-1 rounded-full text-xs transition-colors"
            style={{
              background: !tagFilter ? 'var(--arcis-accent)' : 'var(--arcis-bg-elevated)',
              color: !tagFilter ? 'white' : 'var(--arcis-text-secondary)',
              border: `1px solid ${!tagFilter ? 'var(--arcis-accent)' : 'var(--arcis-border)'}`,
            }}
          >
            All
          </button>
          {allTags.map(tag => (
            <button
              key={tag}
              onClick={() => setTagFilter(tagFilter === tag ? null : tag)}
              className="px-2.5 py-1 rounded-full text-xs transition-colors"
              style={{
                background: tagFilter === tag ? 'var(--arcis-accent)' : 'var(--arcis-bg-elevated)',
                color: tagFilter === tag ? 'white' : 'var(--arcis-text-secondary)',
                border: `1px solid ${tagFilter === tag ? 'var(--arcis-accent)' : 'var(--arcis-border)'}`,
              }}
            >
              {tag}
            </button>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[320px,1fr] gap-4">
        <div className="p-4" style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
          <div className="relative mb-4">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--arcis-text-secondary)' }} />
            <input
              type="text"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search notes..."
              className="w-full pl-9 pr-3 py-2 text-sm"
              style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-primary)', border: '1px solid var(--arcis-border)', color: 'var(--arcis-text-primary)' }}
            />
          </div>

          <div className="space-y-2 max-h-[65vh] overflow-y-auto">
            {filteredNotes.length === 0 ? (
              <div className="text-center py-8">
                <StickyNote size={28} className="mx-auto mb-2" style={{ color: 'var(--arcis-text-muted)' }} />
                <div className="text-sm" style={{ color: 'var(--arcis-text-secondary)' }}>
                  {notes.length === 0 ? 'No notes yet \u2014 add your first note above' : 'No notes match this search.'}
                </div>
              </div>
            ) : (
              filteredNotes.map((note) => {
                const active = note.note_id === selectedId
                return (
                  <button
                    key={note.note_id}
                    onClick={() => setSelectedId(note.note_id)}
                    className="w-full text-left p-3 transition-colors"
                    style={{
                      borderRadius: 'var(--radius-sm)',
                      background: active ? 'rgba(20, 184, 166, 0.12)' : 'var(--arcis-bg-primary)',
                      border: `1px solid ${active ? 'rgba(20, 184, 166, 0.45)' : 'var(--arcis-border)'}`,
                    }}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="font-medium text-sm" style={{ color: 'var(--arcis-text-primary)' }}>
                        {note.title}
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        {note.pinned && (
                          <Pin size={12} style={{ color: 'var(--arcis-warning)' }} />
                        )}
                      </div>
                    </div>
                    <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-muted)' }}>
                      {formatDate(note.updated_at || note.created_at)}
                    </div>
                    <div className="text-xs mt-1.5 leading-relaxed" style={{ color: 'var(--arcis-text-secondary)' }}>
                      {previewText(note.content)}
                    </div>
                    {(note.tags || []).length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {note.tags.map((tag) => (
                          <span
                            key={tag}
                            className="px-1.5 py-0.5 rounded-full text-xs"
                            style={{ background: 'rgba(148, 163, 184, 0.18)', color: 'var(--arcis-text-secondary)' }}
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

        <div className="p-4 md:p-5" style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
          {!selectedNote || !draft ? (
            <div className="h-full min-h-[360px] flex items-center justify-center">
              <div className="text-center">
                <StickyNote size={28} className="mx-auto mb-2" style={{ color: 'var(--arcis-text-muted)' }} />
                <div className="text-sm" style={{ color: 'var(--arcis-text-secondary)' }}>
                  Select a note or create a new one.
                </div>
              </div>
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
                  style={{ borderColor: 'var(--arcis-border)', color: 'var(--arcis-text-primary)', outline: 'none' }}
                />
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setDraft((current) => ({ ...current, pinned: !current.pinned }))}
                    className="inline-flex items-center gap-2 px-3 py-2 text-sm"
                    style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-primary)', border: '1px solid var(--arcis-border)', color: 'var(--arcis-text-primary)' }}
                  >
                    {draft.pinned ? <PinOff size={14} /> : <Pin size={14} />}
                    {draft.pinned ? 'Unpin' : 'Pin'}
                  </button>
                  <button
                    onClick={() => handleDeleteNote(selectedNote.note_id)}
                    className="inline-flex items-center gap-2 px-3 py-2 text-sm"
                    style={{ borderRadius: 'var(--radius-sm)', background: 'rgba(239, 68, 68, 0.12)', border: '1px solid rgba(239, 68, 68, 0.35)', color: 'var(--arcis-danger)' }}
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
                  className="w-full px-3 py-2 text-sm"
                  style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-primary)', border: '1px solid var(--arcis-border)', color: 'var(--arcis-text-primary)' }}
                />
                <div className="px-3 py-2 text-sm flex items-center justify-center" style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-primary)', border: '1px solid var(--arcis-border)', color: 'var(--arcis-text-secondary)' }}>
                  {saveState === 'saving' && 'Saving...'}
                  {saveState === 'pending' && 'Autosave in 2s'}
                  {saveState === 'saved' && 'Saved \u2713'}
                  {saveState === 'error' && 'Save failed'}
                  {saveState === 'idle' && 'Ready'}
                </div>
              </div>

              <textarea
                value={draft.content}
                onChange={(event) => setDraft((current) => ({ ...current, content: event.target.value }))}
                onBlur={flushSave}
                placeholder="Add a note..."
                className="w-full min-h-[420px] px-4 py-3 text-sm leading-relaxed resize-y"
                style={{
                  borderRadius: 'var(--radius-sm)',
                  background: 'var(--arcis-bg-primary)',
                  border: '1px solid var(--arcis-border)',
                  color: 'var(--arcis-text-primary)',
                  outline: 'none',
                  lineHeight: '1.75',
                }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
