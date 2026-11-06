import { useEffect, useState } from 'react'
import { Check } from 'lucide-react'
import { api } from './api'
import type { ResumeResult, Today } from './api'
import {
  Button,
  ButtonLink,
  ErrorLine,
  Page,
  PageHeader,
  RowsSkeleton,
  fmt,
  peekCache,
  primeCache,
} from './ui'

/* Lesson 01: the day's spread — what the course asks of you today. */
export default function TodayPage() {
  /* Seeded from the last visit: coming back to Today paints at once and the
     fresh answer replaces it quietly. */
  const [today, setToday] = useState<Today | null>(() => peekCache<Today>('today'))
  const [error, setError] = useState(false)
  const [pausing, setPausing] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [resumed, setResumed] = useState<ResumeResult | null>(null)

  function load() {
    api
      .today()
      .then((d) => {
        primeCache('today', d)
        setToday(d)
      })
      .catch(() => setError(true))
  }
  useEffect(load, [])

  async function pauseNow() {
    setBusy(true)
    try {
      await api.pauseStart(reason)
      setPausing(false)
      setReason('')
      setResumed(null)
      load()
    } finally {
      setBusy(false)
    }
  }

  async function resume() {
    setBusy(true)
    try {
      setResumed(await api.pauseResume())
      load()
    } finally {
      setBusy(false)
    }
  }

  if (error)
    return (
      <div className="mx-auto max-w-2xl px-6 pt-20 text-center">
        <ErrorLine
          onRetry={() => {
            setError(false)
            load()
          }}
        >
          Today could not be opened. Is the local server running?
        </ErrorLine>
      </div>
    )

  const dateLabel = new Date(`${today?.date ?? new Date().toISOString().slice(0, 10)}T12:00:00`)
    .toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })
  const next = !today || today.pause.paused
    ? null
    : today.review.due > 0 || today.review.new_available > 0
      ? 'review'
      : today.unfinished_reading
        ? 'read'
        : 'practice'

  return (
    <Page width="evidence">
      <PageHeader
        title={dateLabel}
        subtitle={
          today && (
            <>
              Working level{' '}
              <span className="text-cobalt-deep font-semibold">{today.recommendation.level}</span>
              <span className="text-ghost"> — {today.recommendation.reason}</span>
            </>
          )
        }
        meta={
          today &&
          today.streak_days > 0 && (
            <span className="tnum">
              <span className="text-ink font-semibold">{fmt(today.streak_days)}</span> day
              {today.streak_days === 1 ? '' : 's'} studying in a row
            </span>
          )
        }
      />

      {/* Paused: the day becomes a held page, not a list of debts */}
      {today?.pause.paused && (
        <section className="border-cobalt/30 bg-cobalt-wash/50 mt-8 border-l-2 py-5 pl-5">
          <p className="text-cobalt-deep text-xs font-semibold tracking-label uppercase">
            Course on hold
          </p>
          <p className="font-book mt-2 text-xl leading-snug font-semibold">
            Paused since {today.pause.since} — {fmt(today.pause.days)} day
            {today.pause.days === 1 ? '' : 's'}.
            {today.pause.reason && (
              <span className="text-ink-soft font-normal"> {today.pause.reason}.</span>
            )}
          </p>
          <p className="font-book text-ink-soft mt-2 max-w-[64ch] text-base">
            Nothing is piling up: no cards are falling due, no new words are being
            introduced, and <strong className="font-semibold">your streak is safe</strong>.
            When you come back, the backlog is spread over a few days instead of
            landing all at once.
          </p>
          <Button onClick={resume} disabled={busy} className="mt-4">
            {busy ? 'Bringing it back…' : 'Resume the course'}
          </Button>
          {resumed && (
            <p className="font-book text-cobalt-deep mt-3 text-sm">
              Welcome back. {fmt(resumed.cards_spread ?? 0)} cards spread over{' '}
              {fmt(resumed.ramp_days ?? 1)} day{(resumed.ramp_days ?? 1) === 1 ? '' : 's'}
              {resumed.anki?.reachable
                ? ` · ${fmt(resumed.anki.cards)} rescheduled in Anki too`
                : ' · Anki was closed, so its cards were left as they were'}
              .
            </p>
          )}
        </section>
      )}

      {!today ? (
        /* Five rows are coming, so five rows are reserved: no jump. */
        <RowsSkeleton rows={5} rowClass="h-[68px]" className="mt-8" />
      ) : (
        <div className="border-rule mt-8 border-t">
          {/* 1 · Review */}
          <Row
            n="1"
            next={next === 'review'}
            done={today.review.due === 0 && today.review.reviewed_today > 0}
            title="Review your words"
            to="/review"
            cta={today.review.due > 0 ? 'Start reviewing' : 'Open the deck'}
          >
            {today.review.due > 0 ? (
              <>
                <strong className="tnum">{fmt(today.review.due)}</strong> card
                {today.review.due === 1 ? '' : 's'} due
                {today.review.new_available > 0 && (
                  <>
                    {' '}
                    · <strong className="tnum">{fmt(today.review.new_available)}</strong> new
                    word{today.review.new_available === 1 ? '' : 's'} waiting
                  </>
                )}
                {today.review.reviewed_today > 0 && (
                  <span className="text-ghost"> · {fmt(today.review.reviewed_today)} done today</span>
                )}
              </>
            ) : today.review.reviewed_today > 0 ? (
              <>
                Deck clear — <strong className="tnum">{fmt(today.review.reviewed_today)}</strong>{' '}
                reviewed today.
              </>
            ) : (
              <>Nothing due yet. {today.review.new_available > 0 && 'New words are waiting.'}</>
            )}
          </Row>

          {/* 2 · Reading */}
          <Row
            n="2"
            next={next === 'read'}
            done={!today.unfinished_reading && today.reading_minutes_today > 0}
            title="Read"
            to={today.unfinished_reading ? `/reading/${today.unfinished_reading.id}` : '/reading'}
            cta={today.unfinished_reading ? 'Continue reading' : 'Get a reading'}
          >
            {today.unfinished_reading ? (
              <>
                Waiting on the shelf: <em className="font-book">“{today.unfinished_reading.title}”</em>
                {today.unfinished_reading.level && (
                  <span className="text-ghost"> · {today.unfinished_reading.level}</span>
                )}
              </>
            ) : (
              <>Ask the coach to write one with your learning words.</>
            )}
            {today.reading_minutes_today > 0 && (
              <span className="text-ghost">
                {' '}
                · {fmt(Math.round(today.reading_minutes_today))} min read today
              </span>
            )}
          </Row>

          {/* 3 · Practice */}
          <Row n="3" title="Practice" to="/practice" cta="Open practice" next={next === 'practice'}>
            Grammar, vocabulary and listening drills built from your words — all
            multiple choice.
          </Row>

          {/* 4 · Writing */}
          <Row n="4" title="Write" to="/writing" cta="Start writing">
            Reply to a short message, one sentence at a time. Each sentence is checked as you go.
          </Row>

          {/* 5 · Focus */}
          <Row n="5" title="Watch your weak spots">
            {today.error_focus.length > 0 ? (
              <>
                Recent corrections cluster on:{' '}
                {today.error_focus.map((c, i) => (
                  <span key={c}>
                    {i > 0 && ' · '}
                    <span className="text-cobalt-deep font-semibold">{c}</span>
                  </span>
                ))}
              </>
            ) : (
              <>No recurring errors recorded in the last two weeks.</>
            )}
          </Row>

          {/* 6 · The words that are not moving. Naming them is half the fix:
              until now they simply came back, and nothing said why the deck
              felt like it was going nowhere. */}
          {today.stuck_total > 0 && (
            <Row n="6" title="Words that are not moving">
              <>
                {fmt(today.stuck_total)} word{today.stuck_total === 1 ? '' : 's'}{' '}
                keep coming back without settling:{' '}
                {today.stuck_words.slice(0, 6).map((w, i) => (
                  <span key={w.word}>
                    {i > 0 && ' · '}
                    <span className="text-correction font-semibold">{w.word}</span>
                  </span>
                ))}
                {today.stuck_total > 6 && <span className="text-ghost"> …</span>}
                <span className="text-ghost block pt-1">
                  Repeating the card has not moved them, so they now lead the
                  words your readings, activities and podcast are built from —
                  you will meet them in context instead.
                </span>
              </>
            </Row>
          )}

          {/* Can't study for a while? Say so — it costs nothing. */}
          {!today.pause.paused && (
            <div className="mt-6">
              {!pausing ? (
                <Button variant="text" size="sm" onClick={() => setPausing(true)}>
                  Pause the course
                </Button>
              ) : (
                <div className="border-rule flex flex-wrap items-center gap-3 border-t pt-4">
                  <label className="min-w-48 flex-1">
                    <span className="sr-only">Why are you pausing?</span>
                    <input
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      placeholder="Travelling, busy week… (optional)"
                      autoFocus
                      className="border-rule-strong focus:border-cobalt placeholder:text-ghost w-full border-b bg-transparent pb-1 text-sm outline-none"
                    />
                  </label>
                  <Button size="sm" onClick={pauseNow} disabled={busy}>
                    Pause
                  </Button>
                  <Button variant="text" size="sm" onClick={() => setPausing(false)}>
                    Cancel
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </Page>
  )
}

function Row({
  n,
  title,
  children,
  to,
  cta,
  next = false,
  done = false,
}: {
  n: string
  title: string
  children: React.ReactNode
  to?: string
  cta?: string
  next?: boolean
  done?: boolean
}) {
  return (
    <section className="border-rule flex items-baseline gap-4 border-b py-5 sm:gap-6">
      <span className={`tnum w-6 shrink-0 text-right text-sm ${next ? 'text-cobalt-deep font-semibold' : 'text-ghost'}`}>
        {done ? <Check size={16} strokeWidth={1.75} aria-label="Done" className="text-cobalt ml-auto" /> : n}
      </span>
      <div className="grid min-w-0 flex-1 grid-cols-1 items-baseline sm:grid-cols-[minmax(0,1fr)_auto] sm:gap-x-6">
        <h3 className={`font-bold tracking-tight ${next ? 'text-lg' : 'text-base'}`}>{title}</h3>
        <p className="font-book text-ink-soft mt-1 text-base leading-relaxed sm:col-span-2 sm:row-start-2">{children}</p>
        {to && cta && (
          <ButtonLink
            to={to}
            variant={next ? 'primary' : 'text'}
            tone="cobalt"
            size="sm"
            className={`mt-3 justify-self-start pointer-coarse:min-h-11 ${next ? 'sm:row-start-3' : 'sm:col-start-2 sm:row-start-1 sm:mt-0 sm:justify-self-end'}`}
          >
            {cta} →
          </ButtonLink>
        )}
      </div>
    </section>
  )
}
