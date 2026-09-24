import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { api } from './api'
import type { GrammarTip, GuidedResult, WritingResult } from './api'
import { TipCard } from './PracticePage'
import GuidedWriting from './GuidedWriting'
import History from './History'
import { Button, ErrorLine, Page, PageHeader, RuledSkeleton, SLIDE, Section, fmt } from './ui'

/* Lesson 08: the day's single writing task — 4-6 sentences, no more.
   Word count and elapsed time are captured as a by-product (Vision P2). */
export default function WritingPage() {
  const [prompt, setPrompt] = useState<string | null>(null)
  const [focus, setFocus] = useState<string | null>(null)
  const [words, setWords] = useState<string[]>([])
  const [promptError, setPromptError] = useState(false)
  const [text, setText] = useState('')
  const [seconds, setSeconds] = useState(0)
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState<WritingResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tip, setTip] = useState<GrammarTip | null>(null)
  const [mode, setMode] = useState<'guided' | 'free'>('guided')
  const [guided, setGuided] = useState<GuidedResult | null>(null)
  /* Cambia al pedir otra ronda: fuerza un encargo nuevo en vez de reusar el
     estado del anterior. */
  const [round, setRound] = useState(0)
  const timer = useRef<number | undefined>(undefined)

  function loadPrompt() {
    setPrompt(null)
    setPromptError(false)
    api
      .writingPrompt()
      .then((p) => {
        setPrompt(p.prompt)
        setFocus(p.focus)
        setWords(p.learning_words)
      })
      .catch(() => setPromptError(true))
  }

  useEffect(() => {
    loadPrompt()
    return () => window.clearInterval(timer.current)
  }, [])

  function onType(v: string) {
    setText(v)
    if (timer.current === undefined && v.trim()) {
      timer.current = window.setInterval(() => setSeconds((s) => s + 1), 1000)
    }
  }

  async function send() {
    if (wordCount < 5 || sending) return
    window.clearInterval(timer.current)
    setSending(true)
    setError(null)
    try {
      const r = await api.writingSubmit(text, prompt ?? '', seconds)
      setResult(r)
      api.coachTip().then((d) => setTip(d.tip)).catch(() => undefined)
    } catch {
      setError('The coach could not read your text. Try again.')
    } finally {
      setSending(false)
    }
  }

  function reset() {
    setResult(null)
    setText('')
    setSeconds(0)
    timer.current = undefined
    setTip(null)
    loadPrompt()
  }

  const wordCount = text.trim() ? text.trim().split(/\s+/).length : 0
  const clock = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`

  /* Guided is the default. Free writing stays one click away, but it is the
     mode that produced three sessions in four months, so it stops being the
     thing you meet first (M20). */
  if (mode === 'guided' && !result)
    return (
      <Page width="study">
        <PageHeader
          title="Writing"
          meta={
            <Button variant="text" onClick={() => setMode('free')}>
              write freely instead
            </Button>
          }
        />
        {/* El drill se va cuando termina: dejarlo debajo del resumen invita a
            contestar una quinta oración que ya no cuenta para nada. */}
        {guided ? (
          <GuidedSummary
            result={guided}
            onAgain={() => {
              setGuided(null)
              setRound((n) => n + 1)
            }}
          />
        ) : (
          <GuidedWriting key={round} onDone={(r) => setGuided(r)} />
        )}
        <History kind="writing" emptyLabel="nothing written yet" />
      </Page>
    )

  return (
    <Page width="study">
      <PageHeader
        title="Writing"
        meta={
          !result && (
            <Button variant="text" onClick={() => setMode('guided')}>
              guide me sentence by sentence
            </Button>
          )
        }
      />

      {/* The task */}
      <Section
        label={<>Today's task{focus && <span className="text-ghost"> · {focus}</span>}</>}
        right={
          !result && (
            <Button variant="text" size="sm" onClick={loadPrompt}>
              Another task
            </Button>
          )
        }
      >
        {promptError ? (
          <ErrorLine onRetry={loadPrompt}>
            The coach is unavailable — check the AI setup in Reading.
          </ErrorLine>
        ) : prompt ? (
          <>
            <p className="font-book mt-3 text-2xl leading-snug">{prompt}</p>
            {words.length > 0 && (
              <p className="text-ghost mt-2 text-[12px]">
                Try to use:{' '}
                {words.map((w, i) => (
                  <span key={w}>
                    {i > 0 && ' · '}
                    <span className="text-cobalt-deep font-semibold">{w}</span>
                  </span>
                ))}
              </p>
            )}
          </>
        ) : (
          <RuledSkeleton lines={2} />
        )}
      </Section>

      {/* The page you write on */}
      {!result && (
        <Section>
          <label>
            <span className="sr-only">Your text</span>
            <textarea
              value={text}
              onChange={(e) => onType(e.target.value)}
              placeholder="Four to six sentences is plenty…"
              rows={7}
              disabled={!prompt}
              className="font-book border-rule focus:border-cobalt placeholder:text-ghost placeholder:font-ui w-full resize-y border bg-white/60 px-4 py-3 text-[16px] leading-relaxed outline-none disabled:opacity-50"
            />
          </label>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-4">
            <p className="tnum text-ghost text-[12px]">
              {fmt(wordCount)} words · {clock}
            </p>
            <Button onClick={send} disabled={wordCount < 5 || sending}>
              {sending ? 'The coach is reading…' : 'Send to the coach'}
            </Button>
          </div>
          {error && <ErrorLine>{error}</ErrorLine>}
        </Section>
      )}

      {/* The correction */}
      <AnimatePresence>
        {result && (
          <motion.div
            initial={{ y: 16, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={SLIDE}
          >
            <Section>
              <dl className="tnum border-rule grid grid-cols-3 border-b pb-4 text-center">
                <Stat k="Words" v={fmt(result.words_produced)} />
                <Stat k="Time" v={clock} />
                <Stat k="Errors" v={fmt(result.errors.length)} />
              </dl>

              {/* What he asked for: which tenses did I actually use? */}
              <div className="border-rule border-b py-4">
                <p className="text-ghost text-[10px] font-semibold tracking-[0.18em] uppercase">
                  Tenses you used
                </p>
                <p className="font-book mt-1.5 text-[15px]">
                  {result.tenses_used.length > 0 ? (
                    result.tenses_used.map((t, i) => (
                      <span key={t}>
                        {i > 0 && ' · '}
                        <span className="text-cobalt-deep font-semibold">{t}</span>
                      </span>
                    ))
                  ) : (
                    <span className="text-ghost">None identified.</span>
                  )}
                </p>
                <p
                  className={`font-book mt-2 text-[14px] italic ${
                    result.focus_hit ? 'text-cobalt-deep' : 'text-correction'
                  }`}
                >
                  {result.focus_hit ? '✓ ' : '✗ '}
                  {result.focus_note}
                </p>
              </div>

              {result.errors.length > 0 && (
                <>
                  <h3 className="mt-6 text-[12px] font-semibold tracking-[0.18em] uppercase">
                    Corrections
                  </h3>
                  <ul className="mt-3 space-y-4">
                    {result.errors.map((e, i) => (
                      <li key={i} className="border-rule border-b pb-4">
                        <p className="font-book text-correction text-[15px]">✗ {e.original}</p>
                        <p className="font-book text-cobalt-deep mt-1 text-[15px] font-semibold">
                          ✓ {e.correction}
                        </p>
                        <p className="font-book text-ink-soft mt-1.5 text-[13px]">
                          <span className="font-ui text-cobalt-deep mr-2 text-[10px] font-semibold tracking-[0.14em] uppercase">
                            {e.category}
                          </span>
                          {e.explanation}
                        </p>
                      </li>
                    ))}
                  </ul>
                </>
              )}

              <h3 className="mt-6 text-[12px] font-semibold tracking-[0.18em] uppercase">
                Your text at B2
              </h3>
              <p className="font-book mt-2 max-w-[68ch] text-[16px] leading-relaxed">
                {result.improved_version}
              </p>

              <dl className="border-rule mt-6 border-t pt-4 text-[14px]">
                <div className="flex gap-3">
                  <dt className="text-cobalt-deep shrink-0 text-[11px] font-semibold tracking-[0.14em] uppercase">
                    Strength
                  </dt>
                  <dd className="font-book text-ink-soft">{result.strength}</dd>
                </div>
                <div className="mt-2 flex gap-3">
                  <dt className="text-cobalt-deep shrink-0 text-[11px] font-semibold tracking-[0.14em] uppercase">
                    Practice
                  </dt>
                  <dd className="font-book text-ink-soft">{result.practice_next}</dd>
                </div>
              </dl>

              {tip && <TipCard tip={tip} />}

              <Button onClick={reset} className="mt-8">
                Write again
              </Button>
            </Section>
          </motion.div>
        )}
      </AnimatePresence>

      <History kind="writing" emptyLabel="nothing yet" />
    </Page>
  )
}

function Stat({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="text-ghost text-[10px] font-semibold tracking-[0.18em] uppercase">{k}</dt>
      <dd className="text-ink mt-1 text-xl font-extrabold">{v}</dd>
    </div>
  )
}

/* The close of a guided session. Same result-card grammar as Practice and the
   sitting: the number in oversized figures, then what to carry forward. */
function GuidedSummary({
  result,
  onAgain,
}: {
  result: GuidedResult
  onAgain: () => void
}) {
  const minutes = Math.max(1, Math.round(result.seconds / 60))
  return (
    <motion.div
      initial={{ y: 12, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={SLIDE}
    >
      <Section>
        <p className="text-[10px] font-semibold tracking-[0.2em] uppercase">Reply sent</p>
        <p className="tnum mt-3 text-5xl font-extrabold tracking-tight">
          {fmt(result.words_produced)}
          <span className="text-ghost text-2xl font-bold"> words</span>
        </p>
        <p className="font-book text-ink-soft mt-1 text-[14px]">
          {fmt(result.sentences)} sentences in about {fmt(minutes)} minute
          {minutes === 1 ? '' : 's'} · {fmt(result.errors.length)} to fix
        </p>

        <div className="border-cobalt/30 bg-cobalt-wash/40 mt-6 border-l-2 py-4 pl-4">
          <p className="text-cobalt-deep text-[10px] font-semibold tracking-[0.2em] uppercase">
            Your reply
          </p>
          <p className="font-book mt-2 max-w-[62ch] text-[16px] leading-relaxed">
            {result.improved_version}
          </p>
        </div>

        <p className="font-book text-ink-soft mt-4 max-w-[62ch] text-[15px]">
          {result.strength}
        </p>
        <p lang="es" className="font-book text-ghost mt-1 max-w-[62ch] text-[14px] italic">
          {result.practice_next}
        </p>

        <Button variant="secondary" onClick={onAgain} className="mt-7">
          Another one
        </Button>
      </Section>
    </motion.div>
  )
}
