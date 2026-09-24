import { useEffect, useRef, useState } from 'react'
import { api, runJob } from './api'
import type { Episode, PodcastSummary } from './api'
import { Button, ErrorLine, Page, PageHeader, Section, Waiting, fmt, RowsSkeleton, peekCache, primeCache } from './ui'
import { SpeakerIcon, mediaUrl } from './Audio'
import { dayLabel } from './ReadingPage'
import ComprehensionQuiz from './ComprehensionQuiz'

const LENGTHS = [3, 5, 8]
const TOPICS = ['Tech', 'Work', 'AI', 'Fintech', 'Daily Life', 'Random']
const SPEEDS = [0.8, 1] as const
type Mode = 'shadow' | 'ear'

/* Two hosts, two ways to listen: shadow (transcript lit turn by turn) or
   ear only (no text at all, then a quiz that proves you listened). */
export default function PodcastPage() {
  const [items, setItems] = useState<PodcastSummary[] | null>(() =>
    peekCache<PodcastSummary[]>('podcasts'),
  )
  const [episode, setEpisode] = useState<Episode | null>(null)
  const [mode, setMode] = useState<Mode>('shadow')
  const [minutes, setMinutes] = useState(5)
  const [topic, setTopic] = useState('Random')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [stage, setStage] = useState<string | null>(null)

  function load() {
    api
      .podcasts()
      .then((d) => {
        primeCache('podcasts', d.items)
        setItems(d.items)
      })
      .catch(() => setItems([]))
  }
  useEffect(load, [])

  async function generate() {
    if (busy) return
    setBusy(true)
    setError(null)
    setStage('Queued')
    try {
      const job = await runJob('podcast', { minutes, topic }, (j) => {
        const ahead = (j.pending ?? 1) - 1
        setStage(j.status === 'running' ? 'Recording' : ahead > 0 ? `Waiting · ${ahead}` : 'Queued')
      })
      const id = job.result && (job.result as { text_id?: number }).text_id
      if (job.status === 'failed' || !id) throw new Error(job.error ?? 'no episode')
      setEpisode(await api.podcast(id))
      load()
    } catch {
      setError('The studio could not record an episode. Check the AI and voice setup.')
    } finally {
      setBusy(false)
      setStage(null)
    }
  }

  async function open(id: number) {
    setError(null)
    try {
      setEpisode(await api.podcast(id))
    } catch {
      setError('That episode could not be opened.')
    }
  }

  if (episode)
    return (
      <Player
        episode={episode}
        mode={mode}
        setMode={setMode}
        onClose={() => {
          setEpisode(null)
          load()
        }}
      />
    )

  return (
    <Page width="study">
      <PageHeader
        title="Podcast"
        meta={
          items && (
            <span className="tnum">
              {fmt(items.length)} episode{items.length === 1 ? '' : 's'}
            </span>
          )
        }
      />

      <Section label="Record an episode">
        <p className="font-book text-ink-soft mt-1 text-[15px]">
          Two hosts talking, using the words you're learning — listen along with
          the transcript, or with your ears only.
        </p>

        <div className="mt-4 flex flex-wrap items-baseline gap-x-8 gap-y-3">
          <Choice
            label="Length"
            options={LENGTHS.map((m) => `${m} min`)}
            value={`${minutes} min`}
            onPick={(v) => setMinutes(parseInt(v))}
          />
          <Choice label="Topic" options={TOPICS} value={topic} onPick={setTopic} />
        </div>

        <div className="mt-5 flex items-center gap-5">
          <Button onClick={generate} disabled={busy} className="inline-flex items-center gap-2">
            <SpeakerIcon size={13} />
            {busy ? 'Recording…' : 'Record'}
          </Button>
          {busy && (
            <Waiting>
              {stage === 'Recording'
                ? 'Writing the conversation, then giving each host a voice — a few minutes.'
                : stage?.startsWith('Waiting')
                  ? `In line behind ${stage.split('· ')[1]} job(s) — the studio records one at a time.`
                  : 'Queued — starting shortly.'}
            </Waiting>
          )}
        </div>
        {error && <ErrorLine>{error}</ErrorLine>}
      </Section>

      {/* The list painted nothing while it loaded, then popped in. */}
      {items == null && <RowsSkeleton rows={3} className="mt-10" />}

      {/* Episodes, filed by day */}
      {items && items.length > 0 && (
        <div className="mt-10">
          {groupByDay(items).map(([date, list]) => (
            <section key={date} className="mb-6">
              <h3 className="border-rule-strong text-ghost border-b pb-1 text-[10px] font-semibold tracking-[0.2em] uppercase">
                {dayLabel(date)}
              </h3>
              <ul>
                {list.map((p) => (
                  <li key={p.id} className="border-rule border-b">
                    <button
                      onClick={() => open(p.id)}
                      className="hover:bg-cobalt-wash/60 flex w-full items-baseline gap-4 py-3.5 pr-2 pl-1 text-left transition-colors"
                    >
                      <span className="font-book min-w-0 flex-1 truncate text-[16px] font-semibold">
                        {p.title}
                      </span>
                      {p.level && (
                        <span className="text-ghost shrink-0 text-[10px] font-semibold tracking-[0.16em] uppercase">
                          {p.level}
                        </span>
                      )}
                      {p.finished && (
                        <span className="text-cobalt-deep shrink-0 text-[10px] font-semibold tracking-[0.16em] uppercase">
                          heard
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </Page>
  )
}

function groupByDay(items: PodcastSummary[]): [string, PodcastSummary[]][] {
  const map = new Map<string, PodcastSummary[]>()
  for (const it of items) {
    const key = it.date ?? 'undated'
    map.set(key, [...(map.get(key) ?? []), it])
  }
  return [...map.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1))
}

function Player({
  episode,
  mode,
  setMode,
  onClose,
}: {
  episode: Episode
  mode: Mode
  setMode: (m: Mode) => void
  onClose: () => void
}) {
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<number>(1)
  const [current, setCurrent] = useState<number | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [quizOpen, setQuizOpen] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const listened = useRef(0)

  useEffect(() => {
    const el = new window.Audio(mediaUrl(episode.audio))
    el.playbackRate = speed
    el.ontimeupdate = () => {
      setElapsed(el.currentTime)
      const i = episode.marks.findIndex(
        (m) => el.currentTime >= m.start && el.currentTime < m.end,
      )
      setCurrent(i >= 0 ? i : null)
      listened.current = Math.max(listened.current, el.currentTime)
    }
    el.onended = () => {
      setPlaying(false)
      setCurrent(null)
      setQuizOpen(true)
      void api.finishPodcast(episode.id, Math.round(listened.current))
    }
    audioRef.current = el
    return () => {
      el.pause()
      if (listened.current > 5) {
        void api.finishPodcast(episode.id, Math.round(listened.current))
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [episode.id])

  function toggle() {
    const el = audioRef.current
    if (!el) return
    if (playing) {
      el.pause()
      setPlaying(false)
    } else {
      void el.play()
      setPlaying(true)
    }
  }

  function repeatTurn() {
    const el = audioRef.current
    if (!el) return
    const i = current ?? 0
    el.currentTime = episode.marks[i].start
    void el.play()
    setPlaying(true)
  }

  function changeSpeed(s: number) {
    setSpeed(s)
    if (audioRef.current) audioRef.current.playbackRate = s
  }

  const total = episode.marks.length ? episode.marks[episode.marks.length - 1].end : 0
  const clock = (t: number) =>
    `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`

  return (
    <Page width="study">
      <Button variant="text" size="sm" onClick={onClose}>
        ← Episodes
      </Button>

      <PageHeader
        serif
        title={episode.title}
        subtitle={
          <span className="text-ghost text-[12px]">
            {episode.speakers.A} &amp; {episode.speakers.B}
            {episode.level && ` · ${episode.level}`} · {clock(total)}
          </span>
        }
      />

      {/* How do you want to listen? */}
      <div className="border-rule mt-6 flex flex-wrap items-center gap-x-6 gap-y-3 border-y py-3">
        <Button size="sm" onClick={toggle} className="inline-flex items-center gap-2">
          <SpeakerIcon size={13} playing={playing} />
          {playing ? 'Pause' : 'Play'}
        </Button>

        <button
          onClick={repeatTurn}
          className="text-cobalt-deep hover:text-cobalt text-[11px] font-semibold tracking-[0.14em] uppercase"
        >
          Repeat turn
        </button>

        <div className="flex items-baseline gap-2">
          <span className="text-ghost text-[10px] font-semibold tracking-[0.18em] uppercase">
            Speed
          </span>
          {SPEEDS.map((s) => (
            <button
              key={s}
              onClick={() => changeSpeed(s)}
              className={`tnum text-[12px] font-semibold transition-colors ${
                speed === s
                  ? 'text-cobalt-deep underline decoration-2 underline-offset-4'
                  : 'text-ghost hover:text-ink-soft'
              }`}
            >
              {s}×
            </button>
          ))}
        </div>

        <div className="flex items-baseline gap-2">
          <span className="text-ghost text-[10px] font-semibold tracking-[0.18em] uppercase">
            Mode
          </span>
          {(['shadow', 'ear'] as Mode[]).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`text-[12px] font-semibold transition-colors ${
                mode === m
                  ? 'text-cobalt-deep underline decoration-2 underline-offset-4'
                  : 'text-ghost hover:text-ink-soft'
              }`}
            >
              {m === 'shadow' ? 'Shadowing' : 'Ear only'}
            </button>
          ))}
        </div>

        <span className="tnum text-ghost ml-auto text-[12px]">
          {clock(elapsed)} / {clock(total)}
        </span>
      </div>

      {/* Shadowing: the transcript, lit turn by turn */}
      {mode === 'shadow' ? (
        <div className="mt-8 space-y-4">
          {episode.turns.map((t, i) => {
            const lit = current === i
            return (
              <div
                key={i}
                className={`flex gap-3 rounded-[2px] px-1 py-0.5 transition-colors ${
                  lit ? 'bg-cobalt-wash' : current != null ? 'opacity-55' : ''
                }`}
              >
                <span
                  className={`shrink-0 text-[11px] font-semibold tracking-[0.12em] uppercase ${
                    t.speaker === 'A' ? 'text-cobalt-deep' : 'text-ink-soft'
                  }`}
                  style={{ width: '5.5rem' }}
                >
                  {episode.speakers[t.speaker]}
                </span>
                <p className="font-book min-w-0 flex-1 text-[16px] leading-relaxed">{t.text}</p>
              </div>
            )
          })}
        </div>
      ) : (
        <div className="mt-10 text-center">
          <p className="font-book text-ink-soft text-lg italic">
            No transcript — just listen.
          </p>
          <p className="text-ghost mt-2 text-sm">
            When the episode ends, a few questions will check what you caught.
          </p>
          {episode.words_target.length > 0 && (
            <p className="text-ghost mt-6 text-[12px]">
              Listen out for:{' '}
              {episode.words_target.slice(0, 6).map((w, i) => (
                <span key={w}>
                  {i > 0 && ' · '}
                  <span className="text-cobalt-deep font-semibold">{w}</span>
                </span>
              ))}
            </p>
          )}
        </div>
      )}

      {/* The quiz — the point of ear-only mode */}
      {episode.questions.length > 0 && (
        <div className="mt-10">
          {!quizOpen ? (
            <Button variant="text" tone="cobalt" onClick={() => setQuizOpen(true)}>
              Check what you caught →
            </Button>
          ) : (
            <ComprehensionQuiz
              textId={episode.id}
              questions={episode.questions}
              title="What you caught"
            />
          )}
        </div>
      )}
    </Page>
  )
}

function Choice({
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
      <span className="text-ghost text-[10px] font-semibold tracking-[0.18em] uppercase">
        {label}
      </span>
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
