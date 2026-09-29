import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'motion/react'
import { api } from './api'
import type {
  Job,
  Material,
  Projection,
  RatingName,
  RatingOutcome,
  ReviewCard,
  ReviewQueue,
  SessionMode,
  SessionPlan,
  SessionProgress,
  Settings,
  SpreadResult,
} from './api'
import { PlayButton } from './Audio'
import {
  Button,
  ButtonLink,
  ErrorLine,
  Page,
  PageHeader,
  RowsSkeleton,
  RuledSkeleton,
  SLIDE,
  describeError,
  fmt,
} from './ui'

const MINUTES = [10, 20, 30]

/* Lesson 05: the recall drill.
   Front = English word (production-first, Vision P1); the answer slides open
   like the workbook's covered column. A sitting is planned before it starts,
   so the header can talk about *this sitting* instead of showing a backlog
   number that only makes you feel behind (ADR-009). */
export default function ReviewPage() {
  const navigate = useNavigate()
  const [queue, setQueue] = useState<ReviewQueue | null>(null)
  const [session, setSession] = useState<SessionProgress | null>(null)
  const [card, setCard] = useState<ReviewCard | null>(null)
  const [revealed, setRevealed] = useState(false)
  const [error, setError] = useState(false)
  const [busy, setBusy] = useState(false)
  /* "Stop here": leaving is always allowed and loses nothing — progress is
     the review log, and in auto mode the rest of today's load is still there
     when you come back. */
  const [stopped, setStopped] = useState(false)

  /* Preferencia por dispositivo, no del mazo: vive en localStorage y no en
     `settings`. Encender el audio en el Mac no dice nada sobre estudiar en
     otro sitio. Un almacenamiento capado (ventana privada) no puede tumbar
     la página, así que se lee y se escribe entre try. */
  const [autoAudio, setAutoAudio] = useState(() => {
    try {
      return localStorage.getItem('review.autoAudio') !== '0'
    } catch {
      return true
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem('review.autoAudio', autoAudio ? '1' : '0')
    } catch {
      /* sin almacenamiento la preferencia dura lo que la pestaña */
    }
  }, [autoAudio])

  /* Always front-first, new words included. You cannot recall a word you have
     never seen — but looking at it and *trying* is the ritual, and handing it
     over pre-opened turns the card into a poster (ADR-009 D1). */
  const load = useCallback(() => {
    api
      .reviewQueue()
      .then((q) => {
        setQueue(q)
        setSession(q.session ?? null)
        setCard(q.next)
        setRevealed(false)
      })
      .catch(() => setError(true))
  }, [])

  useEffect(load, [load])

  async function rate(rating: 1 | 2 | 3 | 4) {
    if (!card || busy) return
    setBusy(true)
    try {
      const r = await api.reviewAnswer(card.id, rating)
      setQueue(r.queue)
      setSession(r.session ?? null)
      setCard(r.queue.next)
      setRevealed(false)
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!card) return
      if (!revealed && (e.key === ' ' || e.key === 'Enter')) {
        e.preventDefault()
        setRevealed(true)
      } else if (revealed && ['1', '2', '3', '4'].includes(e.key)) {
        rate(Number(e.key) as 1 | 2 | 3 | 4)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  if (error)
    return (
      <div className="mx-auto max-w-2xl px-6 pt-20 text-center">
        <ErrorLine
          onRetry={() => {
            setError(false)
            load()
          }}
        >
          The review deck could not be opened. Is the local server running?
        </ErrorLine>
      </div>
    )

  const active = session?.active ?? false

  return (
    <Page width="study" bottom="" className="flex min-h-[80vh] flex-col">
      <PageHeader
        title="Review"
        meta={
          active &&
          session && (
            <>
              {/* Answers can pass the plan: a learning card comes back inside
                  the same sitting, so "106 of 82" used to appear and read as a
                  bug. Past the plan, the plan stops being the yardstick. */}
              <p className="tnum">
                {(session.done ?? 0) > (session.planned ?? 0)
                  ? `${fmt(session.done ?? 0)} answered this sitting`
                  : `${fmt(session.done ?? 0)} of ${fmt(session.planned ?? 0)} this sitting`}
              </p>
              {/* The three groups, named. "N left" hides that a learning card
                  comes back in this sitting while a review vanishes for days. */}
              {queue && (
                <p className="tnum text-ghost mt-0.5 text-[11px]">
                  {[
                    queue.new_available > 0 && `${fmt(queue.new_available)} new`,
                    queue.learning > 0 && `${fmt(queue.learning)} learning`,
                    queue.due > 0 && `${fmt(queue.due)} due`,
                  ]
                    .filter(Boolean)
                    .join(' · ') || 'nothing left in the queue'}
                </p>
              )}
            </>
          )
        }
      />

      <div className="flex flex-1 flex-col justify-center pb-16">
        <AnimatePresence mode="wait">
          {queue == null ? (
            /* Until the server says whether a sitting is open, draw neither
               screen: the setup used to paint and then get swapped for the
               card — a double jump on every visit. */
            <RowsSkeleton key="opening" rows={3} rowClass="h-12" />
          ) : !active ? (
            <SessionSetup
              key="setup"
              onStarted={(s) => {
                setSession(s)
                load()
              }}
            />
          ) : card && !stopped ? (
            <motion.div
              key={card.id}
              initial={{ y: 16, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: -16, opacity: 0 }}
              transition={SLIDE}
              className="border-rule-strong border bg-white/70 px-6 py-10 text-center sm:px-10"
            >
              {(card.is_new || card.comeback || queue?.ahead) && (
                <p className="text-cobalt-deep mb-4 text-[10px] font-semibold tracking-[0.24em] uppercase">
                  {card.is_new
                    ? 'New entry'
                    : card.comeback
                      ? 'Coming back — meet it again'
                      : 'Still learning — once more'}
                </p>
              )}
              <p className="font-book flex items-center justify-center gap-3 text-4xl font-semibold">
                {card.word}
                <PlayButton
                  src={card.audio_word}
                  label={`Hear ${card.word}`}
                  size={22}
                  autoPlay={autoAudio}
                />
              </p>
              {card.pronunciation && (
                <p className="text-ghost mt-2 text-[14px]">/{card.pronunciation}/</p>
              )}

              <AnimatePresence initial={false}>
                {revealed ? (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    transition={SLIDE}
                    className="overflow-hidden"
                  >
                    <div className="border-rule mt-6 border-t pt-6">
                      {card.meaning_es && (
                        <p lang="es" className="font-book text-cobalt-deep text-xl">
                          {card.meaning_es}
                        </p>
                      )}
                      {card.meaning_en && (
                        <p className="font-book text-ink-soft mt-2 text-[15px]">{card.meaning_en}</p>
                      )}
                      {card.example_en && (
                        <p className="font-book text-ink-soft mx-auto mt-3 flex max-w-[48ch] items-start justify-center gap-2 text-[15px] italic">
                          <span>“{card.example_en}”</span>
                          <PlayButton
                            src={card.audio_example}
                            label="Hear the example"
                            size={13}
                            className="mt-1"
                          />
                        </p>
                      )}
                    </div>
                  </motion.div>
                ) : null}
              </AnimatePresence>

              <div className="mt-8">
                {!revealed ? (
                  <Button onClick={() => setRevealed(true)}>Uncover answer</Button>
                ) : (
                  <div
                    className="flex flex-wrap justify-center gap-2 sm:gap-3"
                    role="radiogroup"
                    aria-label="Rate your recall"
                  >
                    {RATINGS.map(({ label, hint, tone, value }) => (
                      <RateButton
                        key={value}
                        label={label}
                        hint={hint}
                        tone={tone}
                        outcome={queue?.preview?.ratings[label.toLowerCase() as RatingName]}
                        onClick={() => rate(value)}
                        disabled={busy}
                      />
                    ))}
                  </div>
                )}
              </div>
            </motion.div>
          ) : !stopped && queue?.cooling && queue.resume_at ? (
            <Cooling
              key="cooling"
              resumeAt={queue.resume_at}
              waiting={queue.cooling}
              onReady={load}
            />
          ) : (
            <Finished
              key="done"
              session={session!}
              dueLeft={queue?.due_total ?? 0}
              brake={queue?.brake ?? null}
              onMore={() => {
                setStopped(false)
                load()
              }}
              /* Closing lands on Today, not back on the planning screen. The
                 sitting is over and the day's material is being written;
                 offering "how long do you have?" again reads as if nothing
                 had happened. */
              onClose={() => navigate('/')}
            />
          )}
        </AnimatePresence>

        {active && card && !stopped && (
          <>
            {/* Con la cola vacía, el intervalo del botón sigue siendo el
                scheduling real pero la card vuelve enseguida — esperar diez
                minutos mirando una pantalla vacía no enseña nada. Decirlo
                evita que el número parezca una promesa rota. */}
            {queue?.ahead && queue.due === 0 && queue.new_available === 0 && !queue.brake?.on && (
              <p className="font-book text-ghost mx-auto mt-4 max-w-[46ch] text-center text-[12px] italic">
                Nothing else is due, so these keep coming back until they are
                learned — the interval on each button is what gets scheduled,
                not how long you wait.
              </p>
            )}
            {queue?.brake?.on && (
              <p className="font-book text-ink-soft mx-auto mt-4 max-w-[48ch] text-center text-[12px] italic">
                {queue.brake.note}{' '}
                <button
                  onClick={() => api.keepGoing().then(load).catch(() => undefined)}
                  className="hover:text-ink underline underline-offset-2 transition-colors"
                >
                  Keep going anyway
                </button>
              </p>
            )}
            <p className="tnum text-ghost mt-3 text-center text-[11px]">
              <button
                onClick={() => setStopped(true)}
                className="hover:text-ink-soft underline underline-offset-2 transition-colors"
              >
                stop here
              </button>{' '}
              · space to uncover · 1–4 to rate ·{' '}
              <button
                onClick={() => setAutoAudio((v) => !v)}
                className="hover:text-ink-soft underline underline-offset-2 transition-colors"
              >
                audio {autoAudio ? 'on' : 'off'}
              </button>
            </p>
          </>
        )}
      </div>
    </Page>
  )
}

/* ── Planning the sitting ──────────────────────────────────────────────── */

function SessionSetup({ onStarted }: { onStarted: (s: SessionProgress) => void }) {
  const [plan, setPlan] = useState<SessionPlan | null>(null)
  const [settings, setSettings] = useState<Settings | null>(null)
  const [mode, setMode] = useState<SessionMode>('time')
  /* "Less today" is a choice about TODAY. It travels with the plan and the
     start call and is never written to the saved preferences. */
  const [less, setLess] = useState(false)
  const [minutes, setMinutes] = useState(20)
  const [newCount, setNewCount] = useState(6)
  const [reviewCount, setReviewCount] = useState(25)
  const [projection, setProjection] = useState<Projection | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api
      .sessionPlan({})
      .then((d) => {
        setSettings(d.settings)
        setMode(d.settings.mode)
        setMinutes(d.settings.minutes)
        setNewCount(d.settings.new)
        setReviewCount(d.settings.reviews)
        setPlan(d.plan)
        setLess(d.plan.less ?? false)
      })
      .catch(() => undefined)
  }, [])

  /* Re-plan on every change: the breakdown must always describe the buttons
     as they are now, never the previous choice. */
  useEffect(() => {
    if (!settings) return
    const opts =
      mode === 'auto'
        ? { mode, less }
        : mode === 'time'
          ? { mode, minutes }
          : { mode, new: newCount, reviews: reviewCount }
    api.sessionPlan(opts).then((d) => setPlan(d.plan)).catch(() => undefined)
  }, [settings, mode, minutes, newCount, reviewCount, less])

  /* New words are the lever on tomorrow's queue, so the warning belongs next
     to the dial that sets them — not in a settings screen nobody opens. */
  useEffect(() => {
    if (!settings || mode !== 'counts') return setProjection(null)
    api.backlog(newCount).then((b) => setProjection(b.projection)).catch(() => undefined)
  }, [settings, mode, newCount])

  async function start() {
    if (busy) return
    setBusy(true)
    try {
      /* In counts mode the "New words" number is the DAILY cap too. Otherwise
         asking for 6 quietly gave you 5 (the separate new_per_day setting),
         and "today I study 6 new words" has to mean what it says. */
      await api.patchSettings(
        mode === 'auto'
          ? { mode }
          : mode === 'time'
            ? { mode, minutes }
            : { mode, new: newCount, reviews: reviewCount, new_per_day: newCount },
      )
      const s = await api.sessionStart(
        mode === 'auto'
          ? { mode, less }
          : mode === 'time'
            ? { mode, minutes }
            : { mode, new: newCount, reviews: reviewCount },
      )
      onStarted(s)
    } finally {
      setBusy(false)
    }
  }

  if (plan?.paused)
    return (
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={SLIDE}>
        <div className="border-cobalt/30 bg-cobalt-wash/50 border-l-2 py-4 pl-4">
          <p className="text-cobalt-deep text-[10px] font-semibold tracking-[0.2em] uppercase">
            The course is paused
          </p>
          <p className="font-book text-ink-soft mt-2 text-[15px]">
            Nothing is falling due and nothing new is being introduced. Resume from Today
            whenever you want the deck back.
          </p>
        </div>
      </motion.div>
    )

  const nothing = plan != null && plan.total === 0

  return (
    <motion.div
      initial={{ y: 12, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={SLIDE}
    >
      <h3 className="text-[12px] font-semibold tracking-[0.18em] uppercase">
        {mode === 'auto'
          ? "Today's load"
          : mode === 'time'
            ? 'How long do you have?'
            : 'Set your own numbers'}
      </h3>

      {mode === 'auto' ? (
        /* No dial: the number comes from how he actually studies. The one
           control is for the day he has less in him. */
        <div className="mt-3 flex flex-wrap items-baseline gap-x-5 gap-y-2">
          {[false, true].map((v) => (
            <button
              key={String(v)}
              onClick={() => setLess(v)}
              aria-pressed={less === v}
              className={`font-book text-[15px] transition-colors ${
                less === v
                  ? 'text-cobalt-deep border-cobalt border-b font-semibold'
                  : 'text-ink-soft hover:text-cobalt-deep'
              }`}
            >
              {v ? 'Less today' : 'As proposed'}
            </button>
          ))}
        </div>
      ) : mode === 'time' ? (
        <div className="mt-3 flex flex-wrap items-baseline gap-x-5 gap-y-2">
          {MINUTES.map((m) => (
            <button
              key={m}
              onClick={() => setMinutes(m)}
              className={`font-book text-[15px] transition-colors ${
                m === minutes
                  ? 'text-cobalt-deep border-cobalt border-b font-semibold'
                  : 'text-ink-soft hover:text-cobalt-deep'
              }`}
            >
              {m} min
            </button>
          ))}
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap gap-x-8 gap-y-3">
          <NumberField label="New words" value={newCount} onChange={setNewCount} max={50} />
          <NumberField label="Reviews" value={reviewCount} onChange={setReviewCount} max={200} />
        </div>
      )}

      {/* The breakdown, before you commit to it */}
      <div className="border-rule mt-6 border-t pt-5">
        {plan ? (
          <>
            <p className="tnum font-book text-[19px]">
              {nothing ? (
                <span className="text-ink-soft italic">Nothing to study right now.</span>
              ) : (
                <>
                  {plan.mode === 'auto' && plan.budget != null && (
                    <>
                      <strong className="font-semibold">{fmt(plan.budget)}</strong> answers
                      <span className="text-ghost">, repeats included · </span>
                    </>
                  )}
                  <strong className="font-semibold">{fmt(plan.new)}</strong> new
                  <span className="text-ghost"> · </span>
                  <strong className="font-semibold">{fmt(plan.reviews)}</strong> review
                  {plan.reviews === 1 ? '' : 's'}
                  <span className="text-ghost"> ≈ {plan.estimated_minutes} min</span>
                </>
              )}
            </p>
            {plan.short.map((s, i) => (
              <p key={i} className="font-book text-ghost mt-1 text-[13px] italic">
                {s}
              </p>
            ))}
            {/* Why this load: his own numbers, one line each. */}
            {plan.why && plan.why.length > 0 && (
              <ul className="border-rule mt-3 max-w-[58ch] border-l pl-3">
                {plan.why.map((w, i) => (
                  <li key={i} className="font-book text-ghost text-[13px] leading-relaxed italic">
                    {w}
                  </li>
                ))}
              </ul>
            )}
            {plan.mode === 'auto' && (plan.answered_today ?? 0) > 0 && (
              <p className="font-book text-ink-soft mt-2 text-[13px] italic">
                {fmt(plan.answered_today ?? 0)} already answered today — this is what is left
                of today's load, not a new one.
              </p>
            )}
            {plan.triage && plan.triage.later > 0 && (
              <p className="font-book text-ghost mt-1 text-[13px] italic">
                {fmt(plan.triage.later)} more {plan.triage.later === 1 ? 'is' : 'are'} due — they
                get scheduled over the next {fmt(Math.max(1, plan.triage.days))} day
                {plan.triage.days > 1 ? 's' : ''}, best-remembered first.
              </p>
            )}
            {plan.pace.note && (
              <p className="font-book text-ghost mt-1 text-[13px] italic">{plan.pace.note}</p>
            )}
            {projection?.note && (
              <p className="font-book text-correction mt-2 max-w-[58ch] text-[13px] italic">
                {projection.note}
                {projection.reviews_per_word.measured
                  ? ` — your words have taken ${projection.reviews_per_word.value} reviews each so far.`
                  : ' — estimated, you have not reviewed enough words to measure it yet.'}
              </p>
            )}
          </>
        ) : (
          <RuledSkeleton lines={2} />
        )}
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-3">
        <Button onClick={start} disabled={busy || nothing}>
          Start the sitting
        </Button>
        {(['auto', 'time', 'counts'] as SessionMode[])
          .filter((m) => m !== mode)
          .map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className="text-ghost hover:text-cobalt-deep text-[12px] transition-colors"
            >
              {m === 'auto'
                ? 'propose it for me'
                : m === 'time'
                  ? 'choose by time'
                  : 'set exact numbers'}
            </button>
          ))}
      </div>
    </motion.div>
  )
}

function NumberField({
  label,
  value,
  onChange,
  max,
}: {
  label: string
  value: number
  onChange: (n: number) => void
  max: number
}) {
  return (
    <label className="block">
      <span className="text-ghost block text-[10px] font-semibold tracking-[0.2em] uppercase">
        {label}
      </span>
      <input
        type="number"
        min={0}
        max={max}
        value={value}
        onChange={(e) => onChange(Math.max(0, Math.min(max, Number(e.target.value) || 0)))}
        className="tnum border-rule focus:border-cobalt mt-1 w-24 border-b bg-transparent pb-1 text-[19px] outline-none"
      />
    </label>
  )
}

/* ── Closing the sitting ───────────────────────────────────────────────── */

function Cooling({
  resumeAt,
  waiting,
  onReady,
}: {
  resumeAt: string
  waiting: number
  onReady: () => void
}) {
  const target = new Date(resumeAt).getTime()
  const [left, setLeft] = useState(() => Math.max(0, target - Date.now()))

  /* La sentada NO se cierra aquí: quedan palabras, sólo que todavía no toca.
     Cerrarla sería el bug de siempre con otra cara — decir "listo" con
     trabajo pendiente y expulsarte con la palabra peor sabida. */
  useEffect(() => {
    const t = setInterval(() => {
      const ms = Math.max(0, target - Date.now())
      setLeft(ms)
      if (ms === 0) onReady()
    }, 500)
    return () => clearInterval(t)
  }, [target, onReady])

  const secs = Math.ceil(left / 1000)

  return (
    <motion.div
      key="cooling"
      initial={{ y: 12, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={SLIDE}
      className="text-center"
    >
      <p className="text-[10px] font-semibold tracking-[0.2em] uppercase">Taking a breath</p>
      <p className="tnum mt-3 text-5xl font-extrabold tracking-tight">
        {Math.floor(secs / 60)}:{String(secs % 60).padStart(2, '0')}
      </p>
      <p className="font-book text-ink-soft mx-auto mt-4 max-w-[46ch] text-[14px]">
        {fmt(waiting)} word{waiting === 1 ? '' : 's'} still on the ladder. They come back on
        their own — answering one seconds after you just saw it does not prove you know it,
        it only teaches the scheduler that you do not.
      </p>

      {/* A countdown with no way out is a locked door. The reading is the one
          thing worth doing in the two minutes the ladder needs. */}
      <div className="mt-6">
        <ButtonLink to="/reading" variant="text" tone="cobalt">
          Read while you wait →
        </ButtonLink>
      </div>
    </motion.div>
  )
}

function Finished({
  session,
  dueLeft,
  brake,
  onMore,
  onClose,
}: {
  session: SessionProgress
  dueLeft: number
  brake: ReviewQueue['brake']
  onMore: () => void
  onClose: () => void
}) {
  const done = session.done ?? 0
  const [pulling, setPulling] = useState(false)
  const [noMore, setNoMore] = useState(false)

  /* The spread protects from a wall; this is the way back on a day with
     energy to spare. It lands on the planning screen with the cards due. */
  function studyMore() {
    if (pulling) return
    setPulling(true)
    const more =
      session.mode === 'auto'
        ? api.loadMore(20).then(() => ({ pulled: 1 }))
        : api.pullForward(20)
    more
      .then((r) => (r.pulled > 0 ? onMore() : setNoMore(true)))
      .catch(() => undefined)
      .finally(() => setPulling(false))
  }
  const [spread, setSpread] = useState<SpreadResult | null>(null)
  const [material, setMaterial] = useState<Material | null>(null)

  /* Closing the sitting is what tidies the backlog AND queues the day's
     material (ADR-011), so it happens when the card appears — not when you
     click away, where you would never see it. */
  useEffect(() => {
    api
      .sessionEnd()
      .then((r) => {
        setSpread(r.backlog ?? null)
        setMaterial(r.material ?? null)
      })
      .catch(() => undefined)
  }, [])

  const left = spread?.spread ? (spread.kept_today ?? 0) : dueLeft

  return (
    <motion.div
      key="done"
      initial={{ y: 12, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={SLIDE}
      className="text-center"
    >
      <p className="text-[10px] font-semibold tracking-[0.2em] uppercase">Sitting complete</p>
      <p className="tnum mt-3 text-5xl font-extrabold tracking-tight">{fmt(done)}</p>
      <p className="font-book text-ink-soft mt-1 text-[15px]">
        {fmt(session.done_new ?? 0)} new · {fmt(session.done_reviews ?? 0)} reviewed
      </p>

      {brake?.on && (
        <p className="font-book text-ink-soft mx-auto mt-4 max-w-[46ch] text-[13px] italic">
          Stopped early on purpose: {fmt(brake.again)} of {fmt(brake.reviews)} slipped, and
          what was left was harder still. It is kept for a day it can stick.
        </p>
      )}

      {spread?.spread ? (
        <>
          <p className="font-book text-ink-soft mx-auto mt-4 max-w-[46ch] text-[13px] italic">
            More was due than fits in a day, so {fmt(spread.cards ?? 0)} cards were spread
            over the next {fmt(spread.days ?? 0)} day{spread.days === 1 ? '' : 's'}. You will
            see them a little later than the schedule wanted — that is the price of not
            meeting a wall.
          </p>
          {spread.over_capacity && (
            <p className="font-book text-correction mx-auto mt-2 max-w-[46ch] text-[13px] italic">
              Even spread out, that is about {fmt(spread.per_day ?? 0)} a day — more than
              the {fmt(spread.capacity ?? 0)} you planned for. Either sit for longer, or
              pause new words until this drains.
            </p>
          )}
        </>
      ) : (
        left > 0 &&
        !brake?.on && (
          <p className="font-book text-ghost mx-auto mt-4 max-w-[42ch] text-[13px] italic">
            {fmt(left)} still due today. They are not going anywhere — start another
            sitting if you feel like it.
          </p>
        )
      )}

      <TodaysMaterial material={material} />

      <div className="mt-7 flex flex-wrap items-center justify-center gap-x-6 gap-y-3">
        <Button variant="secondary" onClick={onClose}>
          Close the sitting
        </Button>
        <ButtonLink to="/reading" variant="text" tone="cobalt">
          Go read something →
        </ButtonLink>
        {!brake?.on && (left === 0 || session.mode === 'auto') && !noMore && (
          <button
            onClick={studyMore}
            disabled={pulling}
            className="text-ghost hover:text-ink-soft text-[13px] underline underline-offset-2 transition-colors disabled:opacity-50"
          >
            Study 20 more
          </button>
        )}
      </div>
      {noMore && (
        <p className="font-book text-ghost mt-3 text-[13px] italic">
          Nothing else is scheduled for the next two weeks.
        </p>
      )}
    </motion.div>
  )
}


/* The real reward of finishing a sitting is invisible without this: closing it
   queues the day's reading, drill, message and tip, and until M23 the screen
   dropped that answer on the floor. Four jobs could fail in silence and the
   next screen would just say "check the AI setup". */
function TodaysMaterial({ material }: { material: Material | null }) {
  const ids = material?.queued ?? []
  const idsKey = ids.join(',')
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [retried, setRetried] = useState(false)

  useEffect(() => {
    if (!idsKey) return
    let live = true
    let timer: ReturnType<typeof setTimeout>
    const key = new Set(idsKey.split(',').map(Number))
    async function tick() {
      try {
        const r = await api.jobs()
        if (!live) return
        const mine = r.jobs.filter((j) => key.has(j.id))
        setJobs(mine)
        if (mine.some((j) => j.status === 'queued' || j.status === 'running'))
          timer = setTimeout(tick, 2000)
      } catch {
        /* The page's own error path owns a dead server. */
      }
    }
    tick()
    return () => {
      live = false
      clearTimeout(timer)
    }
  }, [idsKey])

  /* `session.end` itself could not ask — worth saying plainly. */
  if (material?.error)
    return (
      <p className="font-book text-correction mx-auto mt-6 max-w-[46ch] text-[13px] italic">
        Today's material could not be requested. It will be waiting on the shelf once the
        coach is back.
      </p>
    )

  if (ids.length === 0) return null

  const failed = jobs?.filter((j) => j.status === 'failed') ?? []
  const working = jobs?.filter((j) => j.status === 'queued' || j.status === 'running') ?? []

  if (failed.length > 0 && working.length === 0)
    return (
      <div className="mx-auto mt-6 max-w-[46ch]">
        <p className="font-book text-correction text-[13px] italic">
          {describeError(
            failed[0].error,
            'The coach could not write today\u2019s material.',
          )}
        </p>
        {!retried && (
          <Button
            variant="text"
            tone="cobalt"
            className="mt-2"
            onClick={() => {
              setRetried(true)
              failed.forEach((j) => api.enqueue(j.kind, j.params).catch(() => undefined))
            }}
          >
            Ask again
          </Button>
        )}
        {retried && <p className="text-ghost mt-2 text-[11px]">Asked again.</p>}
      </div>
    )

  if (working.length > 0 || jobs === null)
    return (
      <p
        role="status"
        aria-live="polite"
        className="font-book text-ghost mx-auto mt-6 max-w-[46ch] text-[13px] italic"
      >
        Your reading, drill and message are being written — one at a time, so the laptop
        stays cool. You can close this and they will be waiting.
      </p>
    )

  return (
    <p className="font-book text-ghost mx-auto mt-6 max-w-[46ch] text-[13px] italic">
      Today\u2019s reading, drill and message are ready.
    </p>
  )
}

/* The four buttons, in the order Again < Hard < Good < Easy. */
const RATINGS = [
  { label: 'Again', hint: '1', tone: 'again', value: 1 },
  { label: 'Hard', hint: '2', tone: 'mid', value: 2 },
  { label: 'Good', hint: '3', tone: 'mid', value: 3 },
  { label: 'Easy', hint: '4', tone: 'easy', value: 4 },
] as const

function RateButton({
  label,
  hint,
  tone,
  outcome,
  onClick,
  disabled,
}: {
  label: string
  hint: string
  tone: 'again' | 'mid' | 'easy'
  outcome?: RatingOutcome
  onClick: () => void
  disabled: boolean
}) {
  const styles = {
    again: 'border-correction/50 text-correction hover:bg-correction/10',
    mid: 'border-rule-strong text-ink-soft hover:border-cobalt/50 hover:text-cobalt-deep',
    easy: 'border-cobalt/50 text-cobalt-deep hover:bg-cobalt-wash',
  }[tone]
  return (
    <div className="flex flex-col items-center gap-1">
      {/* The interval sits ABOVE the button, the way Anki does it: it is a
          property of the choice, not a caption on the result. It says when
          the card comes back, never how long you have been studying it. */}
      <span
        className={`tnum text-[11px] ${
          outcome ? 'text-ghost' : 'text-transparent'
        }`}
        aria-hidden={!outcome}
      >
        {outcome?.interval ?? '·'}
      </span>
      <button
        onClick={onClick}
        disabled={disabled}
        aria-label={outcome ? `${label} — next in ${outcome.interval}` : label}
        className={`rounded-sm border px-4 py-2 text-[12px] font-semibold tracking-[0.12em] uppercase transition-colors disabled:opacity-40 ${styles}`}
      >
        {label}
        <span className="tnum text-ghost ml-1.5 text-[10px]">{hint}</span>
      </button>
      {/* Graduation is worth naming: it is the card leaving the minutes
          behind for good. */}
      <span
        className={`text-[9px] font-semibold tracking-[0.14em] uppercase ${
          outcome?.graduates ? 'text-cobalt-deep' : 'text-transparent'
        }`}
        aria-hidden={!outcome?.graduates}
      >
        graduates
      </span>
    </div>
  )
}
