import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import { Search } from 'lucide-react'

function renderMarkdown(md) {
  if (!md) return ''
  const lines = md.split('\n')
  const html = []
  let inCode = false
  let codeLines = []
  let inList = false

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]

    if (line.startsWith('```')) {
      if (inCode) {
        html.push(`<pre style="background:var(--slate-800);border:1px solid var(--slate-600);border-radius:var(--radius-lg);padding:1rem;overflow-x:auto;font-size:0.875rem;font-family:var(--font-mono);margin:0.75rem 0">${codeLines.join('\n')}</pre>`)
        codeLines = []
        inCode = false
      } else {
        if (inList) { html.push('</ul>'); inList = false }
        inCode = true
      }
      continue
    }

    if (inCode) {
      codeLines.push(line.replace(/</g, '&lt;').replace(/>/g, '&gt;'))
      continue
    }

    if (line.match(/^#{1,6}\s/)) {
      if (inList) { html.push('</ul>'); inList = false }
      const level = line.match(/^(#+)/)[1].length
      const text = line.replace(/^#+\s*/, '')
      const sizes = { 1: 'text-xl font-medium mt-8 mb-3', 2: 'text-lg font-medium mt-6 mb-2', 3: 'text-base font-medium mt-4 mb-2' }
      const cls = sizes[level] || 'text-sm font-medium mt-3 mb-1'
      html.push(`<h${level} class="${cls}" style="color:var(--slate-100)">${inline(text)}</h${level}>`)
      continue
    }

    if (line.match(/^[-*]\s/)) {
      if (!inList) { html.push('<ul class="list-disc list-inside space-y-1 my-2 text-sm" style="color:var(--slate-300)">'); inList = true }
      html.push(`<li>${inline(line.replace(/^[-*]\s*/, ''))}</li>`)
      continue
    }

    if (line.match(/^\d+\.\s/)) {
      if (!inList) { html.push('<ul class="list-decimal list-inside space-y-1 my-2 text-sm" style="color:var(--slate-300)">'); inList = true }
      html.push(`<li>${inline(line.replace(/^\d+\.\s*/, ''))}</li>`)
      continue
    }

    if (inList && line.trim() === '') { html.push('</ul>'); inList = false; continue }
    if (inList && !line.match(/^\s/)) { html.push('</ul>'); inList = false }

    // Table support: lines starting with |
    if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
      const cells = line.split('|').slice(1, -1).map(c => c.trim())
      // Skip separator rows (|---|---|)
      if (cells.every(c => c.match(/^[-:]+$/))) continue
      // Detect if this is a header row (first table row before separator)
      const nextLine = i + 1 < lines.length ? lines[i + 1] : ''
      const isHeader = nextLine.trim().startsWith('|') && nextLine.split('|').slice(1, -1).every(c => c.trim().match(/^[-:]+$/))
      const tag = isHeader ? 'th' : 'td'
      const style = isHeader
        ? 'padding:0.5rem 0.75rem;text-align:left;font-weight:500;color:var(--slate-200);border-bottom:2px solid var(--slate-500)'
        : 'padding:0.5rem 0.75rem;color:var(--slate-300);border-bottom:1px solid var(--slate-700)'
      const rowHtml = cells.map(c => `<${tag} style="${style}">${inline(c)}</${tag}>`).join('')
      // Wrap in scrollable div for mobile
      if (isHeader || (i === 0 || !lines[i - 1]?.trim().startsWith('|'))) {
        html.push('<div style="overflow-x:auto;margin:0.75rem 0"><table style="width:100%;border-collapse:collapse;font-size:0.8125rem">')
      }
      html.push(`<tr>${rowHtml}</tr>`)
      const nextNonSep = i + (isHeader ? 2 : 1)
      if (nextNonSep >= lines.length || !lines[nextNonSep]?.trim().startsWith('|')) {
        html.push('</table></div>')
      }
      continue
    }

    if (line.match(/^---+$/)) {
      html.push(`<hr style="border-color:var(--slate-600);margin:1.5rem 0" />`)
      continue
    }

    if (line.trim() === '') {
      html.push('<div class="h-3"></div>')
      continue
    }

    html.push(`<p class="text-sm leading-relaxed my-1" style="color:var(--slate-300)">${inline(line)}</p>`)
  }

  if (inList) html.push('</ul>')
  if (inCode) html.push(`<pre style="background:var(--slate-800);border:1px solid var(--slate-600);border-radius:var(--radius-lg);padding:1rem;overflow-x:auto;font-size:0.875rem;font-family:var(--font-mono);margin:0.75rem 0">${codeLines.join('\n')}</pre>`)

  return html.join('\n')
}

function inline(text) {
  return text
    .replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong style="color:var(--slate-100);font-weight:500">$1</strong>')
    .replace(/`(.+?)`/g, '<code style="background:var(--slate-800);padding:0.125rem 0.375rem;border-radius:0.25rem;font-size:0.75rem;font-family:var(--font-mono)">$1</code>')
    .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" style="color:var(--teal-400)" class="hover:underline" target="_blank" rel="noopener">$1</a>')
}

const CATEGORY_ORDER = [
  'Core',
  'Strategy & Markets',
  'Training & Model',
  'Infrastructure',
  'Business & Legal',
  'Deep Research',
  'Uncategorized',
]

export default function Docs() {
  const [activeDoc, setActiveDoc] = useState(null)
  const [search, setSearch] = useState('')
  const { data: docList, isLoading: listLoading } = useQuery({
    queryKey: ['docs-list'],
    queryFn: api.getDocsList,
  })
  const { data: doc, isLoading: docLoading } = useQuery({
    queryKey: ['doc', activeDoc],
    queryFn: () => api.getDoc(activeDoc),
    enabled: !!activeDoc,
  })

  // Group docs by category and filter by search
  const groupedDocs = useMemo(() => {
    const docs = docList || []
    const filtered = search
      ? docs.filter(d => d.title.toLowerCase().includes(search.toLowerCase()))
      : docs
    const groups = {}
    for (const d of filtered) {
      const cat = d.category || 'Uncategorized'
      if (!groups[cat]) groups[cat] = []
      groups[cat].push(d)
    }
    return CATEGORY_ORDER
      .filter(cat => groups[cat]?.length > 0)
      .map(cat => ({ label: cat, docs: groups[cat] }))
  }, [docList, search])

  // Auto-select first doc if none selected
  if (!activeDoc && docList?.length > 0) {
    setActiveDoc(docList[0].id)
  }

  return (
    <div className="max-w-5xl mx-auto">
      {/* Mobile: toggle between doc list and content */}
      <div className="flex flex-col md:flex-row gap-4 md:gap-6">
        {/* Sidebar — full width on mobile, fixed 240px on desktop */}
        <nav className={`w-full md:w-60 md:shrink-0 ${activeDoc && docList?.length > 0 ? 'hidden md:block' : ''}`}>
          <h2 className="text-sm font-medium uppercase tracking-wide mb-3" style={{ color: 'var(--slate-400)' }}>
            Documentation {docList ? `(${docList.length})` : ''}
          </h2>

        {/* Search bar */}
        <div className="relative mb-4">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--slate-400)' }} />
          <input
            type="text"
            placeholder="Search docs..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 rounded-lg text-sm"
            style={{
              background: 'var(--slate-800)',
              border: '1px solid var(--slate-600)',
              color: 'var(--slate-100)',
              outline: 'none',
            }}
          />
        </div>

        {listLoading ? (
          <LoadingSpinner />
        ) : (
          <div className="space-y-4 max-h-[calc(100vh-200px)] overflow-y-auto">
            {groupedDocs.map(g => (
              <div key={g.label}>
                <div className="text-xs uppercase tracking-wide px-3 mb-1" style={{ color: 'var(--slate-400)' }}>{g.label}</div>
                <div className="space-y-0.5">
                  {g.docs.map(d => (
                    <button
                      key={d.id}
                      onClick={() => setActiveDoc(d.id)}
                      className="w-full text-left px-3 py-1.5 rounded-lg text-sm transition-colors"
                      style={{
                        background: activeDoc === d.id ? 'var(--slate-700)' : 'transparent',
                        color: activeDoc === d.id ? 'var(--slate-100)' : 'var(--slate-300)',
                      }}
                    >
                      {d.title}
                      {d.size_kb > 0 && (
                        <span className="ml-1 text-xs" style={{ color: 'var(--slate-500)' }}>
                          {d.size_kb < 1 ? '<1' : Math.round(d.size_kb)}kb
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            ))}
            {groupedDocs.length === 0 && (
              <div className="text-center py-4 text-sm" style={{ color: 'var(--slate-400)' }}>
                {search ? 'No docs match your search' : 'No documents available'}
              </div>
            )}
          </div>
        )}
      </nav>

      <div className="flex-1 min-w-0">
        {activeDoc && (
          <button
            onClick={() => setActiveDoc(null)}
            className="md:hidden mb-3 text-sm px-3 py-1.5 rounded-lg"
            style={{ background: 'var(--slate-700)', color: 'var(--teal-400)', border: '1px solid var(--slate-600)' }}
          >
            ← Back to docs
          </button>
        )}
        {docLoading ? (
          <LoadingSpinner />
        ) : doc ? (
          <div className="rounded-lg p-4 md:p-6" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
            <div
              dangerouslySetInnerHTML={{ __html: renderMarkdown(doc.content) }}
              style={{ overflowWrap: 'break-word', wordBreak: 'break-word' }}
            />
          </div>
        ) : (
          <div className="text-center py-12" style={{ color: 'var(--slate-400)' }}>Select a document</div>
        )}
      </div>
    </div>
    </div>
  )
}
