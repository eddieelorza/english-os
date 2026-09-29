import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'motion/react'
import { api } from './api'
import type { AIStatus, Job, LibraryDay } from './api'
import { SpeakerIcon } from './Audio'
import {
  Page,
  PageHeader,
  Section,
  Button,
  ErrorLine,
  Empty,
  Waiting,
  slide,
  fmt,
  useJobWatch,
  queueNote,
  describeError,
  RowsSkeleton,
  peekCache,
  primeCache,
} from './ui'

/* When the work actually started, for the stopwatch in `Waiting`. The server
   writes local wall-clock ISO without a zone, which `Date.parse` reads as
   local — which is what it is. */
function jobSince(job: Job | null): number | null {
  if (!job) return null
  const t = Date.parse(job.started_at ?? job.created_at)
  return Number.isFinite(t) ? t : null
}

const GEN_LEVELS = ['B1', 'B1+', 'B2']
const GEN_MINUTES = [5, 10, 15]
const GEN_TOPICS = ['Tech', 'Work', 'AI', 'Fintech', 'Daily Life', 'Random']

/* "Today", "Yesterday", then the weekday and date — the file label of a
   course archive, not a raw timestamp. */
export function dayLabel(date: string): string {
  const today = new Date()
  const d = new Date(`${date}T12:00:00`)
  const diff = Math.round(
    (new Date(today.toDateString()).getTime() - new Date(d.toDateString()).getTime()) /
      86400000,
  )
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Yesterday'
  return d.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  })
}

export default function ReadingPage() {
  const [days, setDays] = useState<LibraryDay[] | null>(() =>
    peekCache<LibraryDay[]>('shelf.reading'),
  )
  const [confirming, setConfirming] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [composing, setComposing] = useState(false)
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [creating, setCreating] = useState(false)
  const [aiStatus, setAiStatus] = useState<AIStatus | null>(null)
  const [genLevel, setGenLevel] = useState('B1')
  const [genMinutes, setGenMinutes] = useState(5)
  const [genTopic, setGenTopic] = useState('Random')
  const [genError, setGenError] = useState<string | null>(null)
  const navigate = useNavigate()

  /* The id of the job *this* visit asked for. A reading job can also be in
     flight because the end of a review session queued one, or because another
     tab asked — those we show, but they are not a reason to move anyone. */
  const asked = useRef<number | null>(null)

  /* The wait outlives the screen (M23): the state lives in the worker, not in
     this component, so leaving and coming back re-attaches to the same job. */
  const { job: genJob, pending, follow, clear } = useJobWatch(['reading'], (job) => {
    loadShelf()
    const id = job.result && (job.result as { text_id?: number }).text_id
    if (job.status === 'failed' || !id) {
      setGenError(
        describeError(
          job.error,
          'The coach could not write the lesson. Try again in a moment.',
        ),
      )
      clear()
      return
    }
    /* Navigation, decided: only the visit that pressed the button gets moved
       to the finished text. The watch already stops when the screen unmounts,
       so we never navigate from a dead component; the `asked` guard covers the
       other half — a job you are merely watching (queued by session end, or by
       another tab) finishes on the shelf, quietly, where you can choose it. */
    if (asked.current === job.id) navigate(`/reading/${id}`)
    else clear()
  })

  const generating = genJob != null && (genJob.status === 'queued' || genJob.status === 'running')

  const [recommended, setRecommended] = useState<string | null>(null)

  function loadShelf() {
    api
      .library('reading')
      .then((d) => {
        const shelf = d.days.filter((x) => x.reading.length > 0)
        primeCache('shelf.reading', shelf)
        setDays(shelf)
      })
      .catch(() => setError('The reading shelf could not be opened. Is the local server running?'))
  }

  async function remove(id: number, title: string) {
    if (confirming !== id) {
      setConfirming(id)
      window.setTimeout(() => setConfirming((c) => (c === id ? null : c)), 4000)
      return
    }
    setConfirming(null)
    await api.deleteText(id).catch(() => undefined)
    void title
    loadShelf()
  }

  useEffect(() => {
    loadShelf()
    api.aiStatus().then(setAiStatus).catch(() => undefined)
    api
      .model()
      .then((m) => {
        setRecommended(m.recommendation.level)
        setGenLevel(m.recommendation.level)
      })
      .catch(() => undefined)
  }, [])

  async function generate() {
    if (generating) return
    setGenError(null)
    try {
      const job = await api.enqueue('reading', {
        level: genLevel,
        minutes: genMinutes,
        topic: genTopic,
      })
      asked.current = job.id
      follow(job)
    } catch (e) {
      setGenError(
        describeError(
          e instanceof Error ? e.message : null,
          'The lesson could not be ordered. Is the local server running?',
        ),
      )
    }
  }

  async function start() {
    if (!body.trim() || creating) return
    setCreating(true)
    try {
      const t = await api.createText({ title: title.trim() || undefined, body })
      navigate(`/reading/${t.id}`)
    } finally {
      setCreating(false)
    }
  }

  const wordCount = body.trim() ? body.trim().split(/\s+/).length : 0

  return (
    <Page width="ledger">
      <PageHeader
        title="Reading"
        meta={
          days && (
            <span className="tnum">
              {fmt(days.reduce((n, d) => n + d.reading.length, 0))} texts ·{' '}
              {fmt(days.length)} day{days.length === 1 ? '' : 's'}
            </span>
          )
        }
      />

      {/* Today's lesson, written for you */}
      <Section label="Lesson written for you">
        {aiStatus && !aiStatus.configured ? (
          <p className="font-book text-ink-soft mt-2 max-w-[64ch] text-[14px] italic">
            The coach needs a model to write with. Set{' '}
            <code className="font-ui text-cobalt-deep text-[12px]">ANTHROPIC_API_KEY</code> in .env,
            or run Ollama locally (<code className="font-ui text-cobalt-deep text-[12px]">ollama serve</code>{' '}
            + pull a model) — then this panel wakes up.
          </p>
        ) : (
          <>
            <div className="mt-3 flex flex-wrap items-baseline gap-x-8 gap-y-3">
              <GenChoice
                label={recommended && genLevel === recommended ? 'Level ·  coach’s pick' : 'Level'}
                options={GEN_LEVELS}
                value={genLevel}
                onPick={(v) => setGenLevel(v)}
              />
              <GenChoice
                label="Length"
                options={GEN_MINUTES.map((m) => `${m} min`)}
                value={`${genMinutes} min`}
                onPick={(v) => setGenMinutes(parseInt(v))}
              />
              <GenChoice label="Topic" options={GEN_TOPICS} value={genTopic} onPick={(v) => setGenTopic(v)} />
            </div>
            <div className="mt-4">
              <Button variant="primary" onClick={generate} disabled={generating}>
                {generating ? 'The coach is writing…' : 'Write my reading'}
              </Button>
            </div>
            {generating && genJob && (
              <Waiting
                since={jobSince(genJob)}
                note={
                  genJob.status === 'running'
                    ? 'Weaving your learning words into a story — this takes a moment.'
                    : queueNote(genJob, pending)
                }
              >
                {asked.current === genJob.id
                  ? 'The coach is writing…'
                  : 'The coach is already writing a reading for today…'}
              </Waiting>
            )}
            {genError && <ErrorLine onRetry={generate}>{genError}</ErrorLine>}
          </>
        )}
      </Section>

      {/* Composer: paste any English text */}
      <Section>
        {!composing ? (
          <button
            onClick={() => setComposing(true)}
            className="border-cobalt/40 text-cobalt-deep hover:bg-cobalt-wash w-full rounded-sm border border-dashed px-4 py-5 text-left transition-colors"
          >
            <span className="text-[12px] font-semibold tracking-[0.18em] uppercase">
              New reading
            </span>
            <span className="font-book text-ink-soft mt-1 block text-[15px] italic">
              Paste any English text — an article, an email, a chapter — and read it with your
              vocabulary highlighted.
            </span>
          </button>
        ) : (
          <motion.div {...slide()}>
            <label className="border-rule-strong focus-within:border-cobalt block border-b pb-1.5">
              <span className="sr-only">Title</span>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Title (optional)"
                className="placeholder:text-ghost w-full bg-transparent text-[15px] font-semibold outline-none"
              />
            </label>
            <label className="mt-4 block">
              <span className="sr-only">Text to read</span>
              <textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder="Paste your English text here…"
                rows={8}
                autoFocus
                className="font-book border-rule focus:border-cobalt placeholder:text-ghost placeholder:font-ui w-full resize-y border bg-white/60 px-4 py-3 text-[16px] leading-relaxed outline-none"
              />
            </label>
            <div className="mt-3 flex items-center justify-between">
              <p className="tnum text-ghost text-[12px]">{fmt(wordCount)} words</p>
              <div className="flex gap-4">
                <Button variant="text" onClick={() => setComposing(false)}>
                  Cancel
                </Button>
                <Button variant="primary" onClick={start} disabled={!body.trim() || creating}>
                  {creating ? 'Opening…' : 'Start reading'}
                </Button>
              </div>
            </div>
          </motion.div>
        )}
      </Section>

      {/* The shelf, filed by day */}
      <div className="mt-8">
        {error && (
          <ErrorLine
            onRetry={() => {
              setError(null)
              loadShelf()
            }}
          >
            {error}
          </ErrorLine>
        )}
        {days == null && !error && <RowsSkeleton rows={4} rowClass="h-12" />}
        {days && days.length === 0 && !error && (
          <Empty hint="Paste your first text above to begin.">The shelf is empty.</Empty>
        )}
        {days?.map((day) => (
          <section key={day.date} className="mb-8">
            <h3 className="border-rule-strong text-ghost border-b pb-1 text-[10px] font-semibold tracking-[0.2em] uppercase">
              {dayLabel(day.date)}
            </h3>
            <ul>
              {day.reading.map((t) => (
                <li
                  key={t.id}
                  className="border-rule hover:bg-cobalt-wash/60 group flex items-baseline gap-4 border-b py-3.5 pr-2 pl-1 transition-colors"
                >
                  <Link
                    to={`/reading/${t.id}`}
                    className="font-book min-w-0 flex-1 truncate text-[16px] font-semibold"
                  >
                    {t.title}
                  </Link>
                  {t.level && (
                    <span className="text-ghost shrink-0 text-[10px] font-semibold tracking-[0.16em] uppercase">
                      {t.level}
                    </span>
                  )}
                  {t.narrated && (
                    <span className="text-ghost shrink-0" title="Has narration">
                      <SpeakerIcon size={12} />
                    </span>
                  )}
                  {t.finished && (
                    <span className="text-cobalt-deep shrink-0 text-[10px] font-semibold tracking-[0.16em] uppercase">
                      read
                    </span>
                  )}
                  <button
                    onClick={() => remove(t.id, t.title)}
                    aria-label={`Delete ${t.title}`}
                    title="Delete this reading"
                    className={`shrink-0 text-[11px] font-semibold tracking-[0.14em] uppercase transition-opacity ${
                      confirming === t.id
                        ? 'text-correction opacity-100'
                        : 'text-ghost hover:text-correction opacity-0 group-hover:opacity-100'
                    }`}
                  >
                    {confirming === t.id ? 'Sure?' : 'Delete'}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </Page>
  )
}

function GenChoice({
  label,
  options,
  value,
  onPick,
}: {
  label: string
  options: string[]
  value: string
  onPick: (v: string) => void
}) {
  return (
    <div className="flex items-baseline gap-3">
      <span className="text-ghost text-[10px] font-semibold tracking-[0.18em] uppercase">{label}</span>
      <div className="flex flex-wrap gap-x-3 gap-y-1" role="radiogroup" aria-label={label}>
        {options.map((o) => (
          <button
            key={o}
            role="radio"
            aria-checked={value === o}
            onClick={() => onPick(o)}
            className={`text-[12px] font-semibold transition-colors ${
              value === o
                ? 'text-cobalt-deep underline decoration-2 underline-offset-4'
                : 'text-ghost hover:text-ink-soft'
            }`}
          >
            {o}
          </button>
        ))}
      </div>
    </div>
  )
}
