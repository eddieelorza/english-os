import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'motion/react'
import { Search } from 'lucide-react'
import { api } from './api'
import type { Summary, Word, WordPage, WordStatus, StudiedToday as StudiedTodayT } from './api'
import WordEntry from './WordEntry'
import { Page, PageHeader, RuledSkeleton, ErrorLine, Empty, Button, SLIDE, fmt } from './ui'

const TABS: { label: string; value: WordStatus | '' }[] = [
  { label: 'All', value: '' },
  { label: 'New', value: 'NEW' },
  { label: 'Learning', value: 'LEARNING' },
  { label: 'Familiar', value: 'FAMILIAR' },
  { label: 'Mastered', value: 'MASTERED' },
]

const PER_PAGE = 50

export default function VocabularyPage() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [data, setData] = useState<WordPage | null>(null)
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<WordStatus | ''>('')
  const [page, setPage] = useState(1)
  const [openId, setOpenId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const debounce = useRef<number | undefined>(undefined)

  useEffect(() => {
    api.summary().then(setSummary).catch(() => undefined)
  }, [])

  const load = useCallback((q: string, s: WordStatus | '', p: number) => {
    setLoading(true)
    setError(null)
    api
      .words({ q, status: s, page: p, perPage: PER_PAGE, sort: s === '' ? 'status' : 'recent' })
      .then((d) => {
        setData(d)
        setLoading(false)
      })
      .catch(() => {
        setError('The ledger could not be read. Is the local server running? Start it with: make dev')
        setLoading(false)
      })
  }, [])

  useEffect(() => {
    load(query, status, page)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, page])

  function onSearch(value: string) {
    setQuery(value)
    window.clearTimeout(debounce.current)
    debounce.current = window.setTimeout(() => {
      setPage(1)
      load(value, status, 1)
    }, 250)
  }

  function onPatched(updated: Word) {
    setData((d) =>
      d ? { ...d, items: d.items.map((w) => (w.id === updated.id ? { ...w, ...updated } : w)) } : d,
    )
    api.summary().then(setSummary).catch(() => undefined)
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PER_PAGE)) : 1
  const c = summary?.words

  return (
    <Page width="ledger">
      {/* Page heading + exact counts, right-aligned like running times */}
      <PageHeader
        title="Vocabulary"
        meta={
          c && (
            <span className="tnum block leading-tight">
              {fmt(c.LEARNING)} learning · {fmt(c.FAMILIAR)} familiar · {fmt(c.MASTERED)} mastered
              <span className="text-ghost"> · {fmt(c.NEW)} new</span>
              <span className="text-ink block font-semibold">
                {fmt(summary!.words_total)} entries in the ledger
              </span>
            </span>
          )
        }
      />

      <StudiedToday />

      {/* Apparatus: ruled search line + status tabs */}
      <div className="mt-8 flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <label className="border-rule-strong focus-within:border-cobalt flex min-w-56 flex-1 items-center gap-2 border-b pb-1.5 transition-colors">
          <Search size={15} strokeWidth={2} className="text-ghost shrink-0" aria-hidden />
          <span className="sr-only">Search the ledger</span>
          <input
            type="search"
            value={query}
            onChange={(e) => onSearch(e.target.value)}
            placeholder="Search word or meaning…"
            className="placeholder:text-ghost w-full bg-transparent text-[15px] outline-none"
          />
        </label>

        <nav aria-label="Filter by status" className="flex flex-wrap gap-x-4 gap-y-2 sm:gap-x-5">
          {TABS.map((t) => {
            const active = status === t.value
            return (
              <button
                key={t.label}
                onClick={() => {
                  setStatus(t.value)
                  setPage(1)
                  setOpenId(null)
                }}
                aria-pressed={active}
                className={`relative pb-1.5 text-[13px] font-semibold tracking-wide uppercase transition-colors ${
                  active ? 'text-cobalt-deep' : 'text-ghost hover:text-ink-soft'
                }`}
              >
                {t.label}
                {active && (
                  <motion.span
                    layoutId="tab-rule"
                    transition={SLIDE}
                    className="bg-cobalt absolute right-0 -bottom-px left-0 h-0.5"
                  />
                )}
              </button>
            )
          })}
        </nav>
      </div>

      {/* The ledger */}
      {error && <ErrorLine onRetry={() => load(query, status, page)}>{error}</ErrorLine>}

      <div className="border-rule mt-6 border-t" role="list" aria-label="Word entries">
        {!error && loading && <RuledSkeleton lines={9} />}

        {!error && !loading && data && data.items.length === 0 && (
          <Empty
            hint={
              <>
                No entries match{query ? ` “${query}”` : ''}
                {status ? ` with status ${status.toLowerCase()}` : ''}.
              </>
            }
          >
            This page of the ledger is blank.
          </Empty>
        )}

        {!error &&
          data?.items.map((w, i) => (
            <WordEntry
              key={w.id}
              word={w}
              index={(page - 1) * PER_PAGE + i + 1}
              open={openId === w.id}
              onToggle={() => setOpenId(openId === w.id ? null : w.id)}
              onPatched={onPatched}
            />
          ))}
      </div>

      {/* Folio */}
      {data && data.total > PER_PAGE && (
        <footer className="tnum mt-8 flex items-center justify-center gap-6 text-[13px]">
          <Button
            variant="text"
            tone="cobalt"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
          >
            ← Prev
          </Button>
          <span className="text-ink-soft">
            page {fmt(page)} of {fmt(totalPages)}
          </span>
          <Button
            variant="text"
            tone="cobalt"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
          >
            Next →
          </Button>
        </footer>
      )}
    </Page>
  )
}

/* What you touched today, at the top of the ledger.
   Three thousand rows cannot answer "what did I do today?" — the ledger is an
   archive, and an archive is the wrong shape for the last few hours. This is
   the answer, newest first, with the ones that fought back named as such.
   It uses the study day (4:00 rollover), so at 00:30 you are still looking at
   last night's session. */
function StudiedToday() {
  const [data, setData] = useState<StudiedTodayT | null>(null)
  const [open, setOpen] = useState(true)

  useEffect(() => {
    api.studiedToday().then(setData).catch(() => undefined)
  }, [])

  if (!data || data.total === 0) return null

  return (
    <section className="mt-8">
      <div className="border-rule-strong flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b pb-1.5">
        <h3 className="text-[12px] font-semibold tracking-[0.18em] uppercase">
          Studied today
        </h3>
        <div className="flex items-baseline gap-4">
          <p className="tnum text-ghost text-[12px]">
            {fmt(data.total)} word{data.total === 1 ? '' : 's'}
            {data.introduced > 0 && ` · ${fmt(data.introduced)} new`}
            {data.struggled > 0 && (
              <span className="text-correction"> · {fmt(data.struggled)} fought back</span>
            )}
          </p>
          <button
            onClick={() => setOpen(!open)}
            className="text-ghost hover:text-cobalt-deep text-[11px] transition-colors"
          >
            {open ? 'hide' : 'show'}
          </button>
        </div>
      </div>

      {open && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {data.items.map((w) => (
            <li key={w.id}>
              <span
                title={`${w.meaning_es ?? ''}${w.times > 1 ? ` · seen ${w.times}×` : ''}`}
                className={`font-book inline-flex items-baseline gap-1.5 rounded-sm border px-2.5 py-1 text-[14px] ${
                  w.worst_rating === 1
                    ? 'border-correction/50 text-correction'
                    : 'border-rule text-ink-soft'
                }`}
              >
                {w.word}
                {w.times > 1 && (
                  <span className="tnum text-ghost text-[10px]">×{fmt(w.times)}</span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      {open && data.struggled > 0 && (
        <p className="font-book text-ghost mt-3 max-w-[68ch] text-[13px] italic">
          The ones in red came back more than once today — those are the ones
          worth meeting again in a reading or an activity, not just another card.
        </p>
      )}
    </section>
  )
}
