import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { api } from './api'
import type { Activity, GrammarTip, Question } from './api'
import { PlayButton } from './Audio'
import History from './History'
import { Button, Choice, Empty, ErrorLine, Page, PageHeader, RuledSkeleton, SLIDE, Section, fmt } from './ui'

const LETTERS = ['A', 'B', 'C']

/* Lesson 07: the drill.
   One question at a time, answered by tap or by key, marked the instant it is
   answered. A worksheet asks you to fill twelve blanks and grades you at the
   end; a drill tells you immediately whether you were right and why, which is
   the only moment the explanation is worth reading. */
export default function PracticePage() {
  const [acts, setActs] = useState<Activity[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tip, setTip] = useState<GrammarTip | null>(null)

  useEffect(() => {
    api
      .activitiesToday()
      .then((d) => setActs(d.activities))
      .catch(() =>
        setError('The coach could not prepare today’s practice. Check the AI setup.'),
      )
    api.coachTip().then((d) => setTip(d.tip)).catch(() => undefined)
  }, [])

  const pending = acts?.filter((a) => !a.completed_at) ?? []
  const finished = acts?.filter((a) => a.completed_at) ?? []

  return (
    <Page width="study">
      <PageHeader title="Practice" />

      {error && <ErrorLine>{error}</ErrorLine>}

      {!acts && !error && <RuledSkeleton lines={4} />}

      {pending.length > 0 && <Drill key={pending[0].id} activities={pending} tip={tip} />}

      {/* Already answered today — the worksheet is the right shape for review */}
      {pending.length === 0 && finished.length > 0 && (
        <>
          <p className="font-book text-ink-soft mt-2 text-[15px]">
            Done for today. Here is what you answered.
          </p>
          {finished.map((a) => (
            <Reviewed key={a.id} activity={a} />
          ))}
          {tip && <TipCard tip={tip} />}
        </>
      )}

      {acts && acts.length === 0 && !error && (
        <Empty>No practice today — study some words first and come back.</Empty>
      )}

      <History kind="activities" emptyLabel="nothing yet" />
    </Page>
  )
}

/* ── The drill ─────────────────────────────────────────────────────────── */

type Step = { activity: Activity; q: Question; qi: number; setIndex: number }

function Drill({ activities, tip }: { activities: Activity[]; tip: GrammarTip | null }) {
  const steps: Step[] = useMemo(
    () =>
      activities.flatMap((activity, setIndex) =>
        activity.questions.map((q, qi) => ({ activity, q, qi, setIndex })),
      ),
    [activities],
  )

  const [i, setI] = useState(0)
  const [picked, setPicked] = useState<number | null>(null)
  /* One slot per step: null until answered, then the option index. */
  const [answers, setAnswers] = useState<(number | null)[]>(() => steps.map(() => null))
  const [done, setDone] = useState(false)
  const started = useRef(Date.now())
  const setStarted = useRef(Date.now())

  const step = steps[i]
  const last = i === steps.length - 1
  const correct = picked != null && picked === step?.q.answer_index

  const submitSet = useCallback(
    (setIndex: number, all: (number | null)[]) => {
      const activity = activities[setIndex]
      const mine = steps
        .map((s, n) => (s.setIndex === setIndex ? all[n] : undefined))
        .filter((v): v is number | null => v !== undefined)
      if (mine.some((v) => v == null)) return
      const seconds = Math.round((Date.now() - setStarted.current) / 1000)
      setStarted.current = Date.now()
      /* Fire and forget: the score is already on screen, and a failed save
         must not interrupt a session in progress. */
      api.activitySubmit(activity.id, mine as number[], seconds).catch(() => undefined)
    },
    [activities, steps],
  )

  const pick = useCallback(
    (oi: number) => {
      if (picked != null || !step) return
      setPicked(oi)
      setAnswers((prev) => {
        const next = prev.map((p, n) => (n === i ? oi : p))
        const lastOfSet = !steps[i + 1] || steps[i + 1].setIndex !== step.setIndex
        if (lastOfSet) submitSet(step.setIndex, next)
        return next
      })
    },
    [picked, step, i, steps, submitSet],
  )

  const advance = useCallback(() => {
    if (picked == null) return
    if (last) setDone(true)
    else setI((n) => n + 1)
    setPicked(null)
  }, [picked, last])

  /* Answer with A/B/C or 1/2/3, continue with Enter or Space — the session
     should run without the hand leaving the keyboard. */
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (done || !step) return
      if (picked == null) {
        const k = e.key.toLowerCase()
        const byLetter = LETTERS.findIndex((l) => l.toLowerCase() === k)
        const byNumber = '123'.indexOf(k)
        const oi = byLetter >= 0 ? byLetter : byNumber
        if (oi >= 0 && oi < step.q.options.length) {
          e.preventDefault()
          pick(oi)
        }
      } else if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        advance()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [done, step, picked, pick, advance])

  if (done)
    return (
      <Result
        steps={steps}
        answers={answers}
        seconds={Math.round((Date.now() - started.current) / 1000)}
        tip={tip}
      />
    )

  if (!step) return null

  const answeredCount = answers.filter((a) => a != null).length

  return (
    <section className="mt-8">
      {/* Where you are: the set, and one thin segment per question */}
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <p className="text-[10px] font-semibold tracking-[0.2em] uppercase">
          {activities.length > 1 && (
            <span className="text-ghost">
              Set {fmt(step.setIndex + 1)} of {fmt(activities.length)} ·{' '}
            </span>
          )}
          {step.activity.title}
        </p>
        <p className="tnum text-ghost text-[12px]">
          {fmt(answeredCount)} / {fmt(steps.length)}
        </p>
      </div>

      <div className="mt-2 flex gap-[3px]" aria-hidden>
        {steps.map((s, n) => (
          <span
            key={n}
            className={`h-[3px] flex-1 rounded-full transition-colors duration-300 ${
              answers[n] == null
                ? 'bg-rule'
                : answers[n] === s.q.answer_index
                  ? 'bg-cobalt'
                  : 'bg-correction/60'
            }`}
          />
        ))}
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={i}
          initial={{ x: 24, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: -24, opacity: 0 }}
          transition={SLIDE}
          className="min-h-[19rem] pt-7"
        >
          <p className="font-book flex items-start gap-2 text-[19px] leading-snug font-semibold">
            <span>{step.q.prompt ?? step.q.question}</span>
            {step.q.audio && (
              <PlayButton src={step.q.audio} label="Play the word" className="mt-1.5" />
            )}
          </p>

          <div
            className="mt-5 space-y-2"
            role="radiogroup"
            aria-label={`Question ${i + 1} of ${steps.length}`}
          >
            {step.q.options.map((opt, oi) => {
              const isAnswer = oi === step.q.answer_index
              const chosen = picked === oi
              return (
                <Choice
                  key={oi}
                  role="radio"
                  aria-checked={chosen}
                  onClick={() => pick(oi)}
                  disabled={picked != null}
                  letter={LETTERS[oi]}
                  state={
                    picked == null
                      ? 'idle'
                      : isAnswer
                        ? 'correct'
                        : chosen
                          ? 'wrong'
                          : 'muted'
                  }
                >
                  {opt}
                </Choice>
              )
            })}
          </div>

          <AnimatePresence>
            {picked != null && (
              <motion.div
                initial={{ y: -6, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={SLIDE}
                className={`mt-4 border-l-2 py-1 pl-3 ${
                  correct ? 'border-cobalt/40' : 'border-correction/40'
                }`}
              >
                <p
                  className={`text-[10px] font-semibold tracking-[0.2em] uppercase ${
                    correct ? 'text-cobalt-deep' : 'text-correction'
                  }`}
                >
                  {correct ? 'Right' : `Not quite — ${LETTERS[step.q.answer_index]}`}
                </p>
                <p className="font-book text-ink-soft mt-1 max-w-[62ch] text-[14px] italic">
                  {step.q.why}
                </p>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Deliberately not autofocused: a focused button turns Enter into a
              native click, which would race the key handler above and skip a
              question. One path in, one advance out. */}
          {picked != null && (
            <Button onClick={advance} className="mt-5">
              {last ? 'Finish' : 'Continue'}
            </Button>
          )}
        </motion.div>
      </AnimatePresence>

      <p className="text-ghost mt-2 text-[11px]">
        {picked == null ? 'Press A, B or C' : 'Press Enter'}
      </p>
    </section>
  )
}

/* ── The closing card ──────────────────────────────────────────────────── */

function Result({
  steps,
  answers,
  seconds,
  tip,
}: {
  steps: Step[]
  answers: (number | null)[]
  seconds: number
  tip: GrammarTip | null
}) {
  const score = steps.filter((s, n) => answers[n] === s.q.answer_index).length
  const missed = steps.filter((s, n) => answers[n] !== s.q.answer_index)
  const minutes = Math.max(1, Math.round(seconds / 60))

  return (
    <motion.div
      initial={{ y: 14, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={SLIDE}
    >
      <Section>
        <p className="text-[10px] font-semibold tracking-[0.2em] uppercase">Practice complete</p>

        <p className="tnum mt-3 text-5xl font-extrabold tracking-tight">
          {fmt(score)}
          <span className="text-ghost text-3xl font-bold"> / {fmt(steps.length)}</span>
        </p>
        <p className="font-book text-ink-soft mt-1 text-[14px]">
          {fmt(steps.length)} question{steps.length === 1 ? '' : 's'} in about {fmt(minutes)}{' '}
          minute{minutes === 1 ? '' : 's'}.
        </p>

        {missed.length > 0 && (
          <div className="mt-6">
            <h3 className="border-rule-strong text-ghost border-b pb-1 text-[10px] font-semibold tracking-[0.2em] uppercase">
              Worth another look
            </h3>
            <ul className="mt-3 space-y-3">
              {missed.slice(0, 4).map((s, n) => (
                <li key={n} className="max-w-[64ch]">
                  <p className="font-book text-[14px] font-semibold">
                    {s.q.prompt ?? s.q.question}
                  </p>
                  <p className="font-book text-cobalt-deep mt-0.5 text-[14px]">
                    {s.q.options[s.q.answer_index]}
                  </p>
                  <p className="font-book text-ink-soft mt-0.5 text-[13px] italic">{s.q.why}</p>
                </li>
              ))}
            </ul>
            {missed.length > 4 && (
              <p className="text-ghost mt-3 text-[12px] italic">
                …and {fmt(missed.length - 4)} more, filed in today’s practice.
              </p>
            )}
          </div>
        )}

        {missed.length === 0 && (
          <p className="font-book text-ink-soft mt-4 max-w-[62ch] text-[15px] italic">
            Nothing missed. Tomorrow’s set will be built from harder words.
          </p>
        )}

        {tip && <TipCard tip={tip} />}
      </Section>
    </motion.div>
  )
}

/* ── Review of an already-answered set ─────────────────────────────────── */

function Reviewed({ activity }: { activity: Activity }) {
  const answers = activity.answers ?? []
  return (
    <Section>
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h3 className="text-[13px] font-bold tracking-tight">{activity.title}</h3>
        <p className="tnum text-ghost text-[12px]">
          {fmt(activity.score ?? 0)} / {fmt(activity.total ?? activity.questions.length)} correct
        </p>
      </div>
      <ol className="mt-4 space-y-5">
        {activity.questions.map((q, qi) => {
          const picked = answers[qi]
          const right = picked === q.answer_index
          return (
            <li key={qi} className="max-w-[66ch]">
              <p className="font-book flex items-start gap-2 text-[15px]">
                <span className="tnum text-ghost shrink-0">{qi + 1}.</span>
                <span>{q.prompt ?? q.question}</span>
              </p>
              <p
                className={`font-book mt-1 pl-6 text-[14px] ${
                  right ? 'text-cobalt-deep font-semibold' : 'text-correction'
                }`}
              >
                {right ? '✓ ' : '✗ '}
                {q.options[picked] ?? '—'}
                {!right && (
                  <span className="text-cobalt-deep font-semibold">
                    {' → '}
                    {q.options[q.answer_index]}
                  </span>
                )}
              </p>
            </li>
          )
        })}
      </ol>
    </Section>
  )
}

export function TipCard({ tip }: { tip: GrammarTip }) {
  return (
    <motion.section
      initial={{ y: 12, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={SLIDE}
      className="border-cobalt/30 bg-cobalt-wash/50 mt-10 border-l-2 py-4 pl-4"
    >
      <p className="text-cobalt-deep text-[10px] font-semibold tracking-[0.2em] uppercase">
        Grammar in one minute · {tip.category}
      </p>
      <p className="font-book mt-2 text-[16px] leading-snug font-semibold">{tip.rule}</p>
      <p className="font-book text-correction mt-3 text-[14px]">✗ {tip.wrong}</p>
      <p className="font-book text-cobalt-deep text-[14px] font-semibold">✓ {tip.right}</p>
      <p className="font-book text-ink-soft mt-2 text-[13px] italic">{tip.remember}</p>
    </motion.section>
  )
}
