import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { api } from './api'
import type { GuidedResult, WritingTask, WrittenSentence } from './api'
import { Button, ErrorLine, RuledSkeleton, SLIDE, Waiting, describeError, fmt } from './ui'

/* Writing, one sentence at a time.
   The evidence behind this shape: three writing sessions in the whole project.
   "Four to six sentences" sounds small but is still an empty box, and an empty
   box is the wall. The one time the writing flowed it was a letter to a person
   ("Hi Arnold…", 77 words) — so: a real recipient, one sentence at a time, and
   the correction right there, which is the Practice drill's shape and the one
   that gets used. */

/* The local record of an answered sentence. `checked` is ours, not the
   server's: when the coach cannot be reached we keep the sentence and say so,
   instead of stamping it "Right as it is" — a green tick nobody earned is
   worse than no tick (M24). The wire shape stays `WrittenSentence`. */
type Feedback = WrittenSentence & { checked: boolean }

function forServer(list: Feedback[]): WrittenSentence[] {
  return list.map(({ ok, fixed, note, category, text }) => ({
    ok,
    fixed,
    note,
    category,
    text,
  }))
}

export default function GuidedWriting({
  onDone,
}: {
  onDone: (r: GuidedResult) => void
}) {
  const [task, setTask] = useState<WritingTask | null>(null)
  /* Three failures, three different sentences. They used to be one boolean
     called `failed`, so losing the closing call told you the setup had gone
     wrong and threw the writing away with it. */
  const [setupError, setSetupError] = useState<string | null>(null)
  const [checkError, setCheckError] = useState<string | null>(null)
  const [finishError, setFinishError] = useState<string | null>(null)
  const [loadingSince, setLoadingSince] = useState<number | null>(() => Date.now())
  const [checkSince, setCheckSince] = useState<number | null>(null)
  const [finishSince, setFinishSince] = useState<number | null>(null)
  const [i, setI] = useState(0)
  const [text, setText] = useState('')
  const [checking, setChecking] = useState(false)
  const [finishing, setFinishing] = useState(false)
  const [done, setDone] = useState<Feedback[]>([])
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const [seconds, setSeconds] = useState(0)
  const timer = useRef<number | undefined>(undefined)
  const box = useRef<HTMLInputElement>(null)

  const loadTask = useCallback(() => {
    setSetupError(null)
    setTask(null)
    setLoadingSince(Date.now())
    api
      .writingSteps()
      .then((t) => {
        setTask(t)
        setLoadingSince(null)
      })
      .catch((e: unknown) => {
        setLoadingSince(null)
        setSetupError(e instanceof Error ? e.message : String(e))
      })
  }, [])

  useEffect(() => {
    loadTask()
    return () => window.clearInterval(timer.current)
  }, [loadTask])

  const step = task?.steps[i]
  /* Every sentence answered: the drill is over even if the close failed, so
     the box and the Check button go away instead of inviting a fifth
     sentence that would be sent twice. */
  const atEnd = task != null && done.length >= task.steps.length

  /* The starter is pre-filled, not placeholder text: he should be *continuing*
     a sentence, never starting one. */
  useEffect(() => {
    if (step) setText(step.starter ? `${step.starter} ` : '')
    box.current?.focus()
  }, [step])

  function startClock() {
    if (timer.current === undefined) {
      timer.current = window.setInterval(() => setSeconds((s) => s + 1), 1000)
    }
  }

  async function checkIt() {
    if (!step || checking || !text.trim()) return
    startClock()
    setChecking(true)
    setCheckError(null)
    setCheckSince(Date.now())
    try {
      const r = await api.writingCheck(text.trim(), step.ask)
      setFeedback({ ...r, text: text.trim(), checked: true })
    } catch (e: unknown) {
      /* Never strand him mid-sentence over a model hiccup: keep what he wrote
         — but keep it as *unchecked*, and offer the check again right here. */
      setCheckError(e instanceof Error ? e.message : String(e))
      setFeedback({
        ok: true,
        fixed: text.trim(),
        note: '',
        text: text.trim(),
        checked: false,
      })
    } finally {
      setChecking(false)
      setCheckSince(null)
    }
  }

  /* Re-run the check on the sentence still on screen. The text box keeps its
     value while the feedback shows, so there is nothing to restore. */
  function retryCheck() {
    setFeedback(null)
    setCheckError(null)
    void checkIt()
  }

  /* The close. It takes every sentence written so far, so the retry after a
     failure sends exactly the same work — nothing is thrown away. */
  async function finish(all: Feedback[]) {
    if (!task || finishing) return
    setFinishing(true)
    setFinishError(null)
    setFinishSince(Date.now())
    try {
      onDone(await api.writingFinish(forServer(all), task.scenario, seconds))
    } catch (e: unknown) {
      setFinishError(e instanceof Error ? e.message : String(e))
    } finally {
      setFinishing(false)
      setFinishSince(null)
    }
  }

  async function next() {
    if (!feedback || !task) return
    const all = [...done, feedback]
    setDone(all)
    setFeedback(null)
    if (i + 1 < task.steps.length) {
      setI(i + 1)
      return
    }
    await finish(all)
  }

  /* The setup failed: there is no message to reply to, so there is no drill.
     This is the only failure that empties the screen. The way out to free
     writing is the header's own switch, one line above — a second copy here
     read as two different actions. */
  if (setupError !== null)
    return (
      <div>
        <ErrorLine onRetry={loadTask}>
          {describeError(
            setupError,
            "The coach could not set up today's message.",
          )}
        </ErrorLine>
      </div>
    )

  if (!task)
    return (
      <>
        <Waiting since={loadingSince}>The coach is writing today's message…</Waiting>
        <RuledSkeleton lines={3} />
      </>
    )

  return (
    <section className="mt-8">
      {/* The message he is replying to — the reason to write at all */}
      <div className="border-cobalt/30 bg-cobalt-wash/40 border-l-2 py-4 pl-4">
        <p className="text-cobalt-deep text-[10px] font-semibold tracking-[0.2em] uppercase">
          From {task.from_name}
        </p>
        <p className="font-book mt-2 max-w-[62ch] text-[16px] leading-relaxed">
          {task.message}
        </p>
        <p lang="es" className="font-book text-ghost mt-2 text-[13px] italic">
          {task.scenario}
        </p>
      </div>

      {/* One segment per sentence, filled as you go. Three states now: right,
          fixed, and — when the coach was unreachable — written but unchecked. */}
      <div className="mt-6 flex gap-[3px]" aria-hidden>
        {task.steps.map((_, n) => (
          <span
            key={n}
            className={`h-[3px] flex-1 rounded-full transition-colors duration-300 ${
              n < done.length
                ? !done[n].checked
                  ? 'bg-rule-strong'
                  : done[n].ok
                    ? 'bg-cobalt'
                    : 'bg-correction/60'
                : 'bg-rule'
            }`}
          />
        ))}
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={i}
          initial={{ x: 20, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: -20, opacity: 0 }}
          transition={SLIDE}
          className="min-h-[15rem] pt-6"
        >
          {!atEnd && (
            <>
              <p className="tnum text-ghost text-[11px]">
                Sentence {fmt(i + 1)} of {fmt(task.steps.length)}
              </p>
              <p lang="es" className="font-book mt-1 max-w-[58ch] text-[17px] font-semibold">
                {step?.ask}
              </p>
              {step?.word && (
                <p className="text-ghost mt-1 text-[12px]">
                  usa <span className="text-cobalt-deep font-semibold">{step.word}</span>
                </p>
              )}

              <input
                ref={box}
                value={text}
                disabled={!!feedback || checking}
                onChange={(e) => {
                  setText(e.target.value)
                  startClock()
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    if (feedback) void next()
                    else void checkIt()
                  }
                }}
                className="font-book border-rule focus:border-cobalt mt-4 w-full border-b bg-transparent pb-2 text-[19px] outline-none disabled:opacity-70"
              />

              {checking && (
                <Waiting since={checkSince}>The coach is reading your sentence…</Waiting>
              )}

              <AnimatePresence>
                {feedback && (
                  <motion.div
                    initial={{ y: -6, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={SLIDE}
                    className={`mt-4 border-l-2 py-1 pl-3 ${
                      !feedback.checked
                        ? 'border-rule-strong'
                        : feedback.ok
                          ? 'border-cobalt/40'
                          : 'border-correction/40'
                    }`}
                  >
                    <p
                      className={`text-[10px] font-semibold tracking-[0.2em] uppercase ${
                        !feedback.checked
                          ? 'text-ghost'
                          : feedback.ok
                            ? 'text-cobalt-deep'
                            : 'text-correction'
                      }`}
                    >
                      {!feedback.checked
                        ? 'Not checked — kept as you wrote it'
                        : feedback.ok
                          ? 'Right as it is'
                          : 'Almost'}
                    </p>
                    {feedback.checked && !feedback.ok && (
                      <p className="font-book text-cobalt-deep mt-1 text-[16px]">
                        {feedback.fixed}
                      </p>
                    )}
                    {feedback.note && (
                      <p lang="es" className="font-book text-ink-soft mt-1 max-w-[58ch] text-[14px] italic">
                        {feedback.note}
                      </p>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Why it was not checked, and the way to check it after all. */}
              {checkError !== null && feedback && !feedback.checked && (
                <ErrorLine onRetry={retryCheck} retryLabel="Check this sentence again">
                  {describeError(
                    checkError,
                    'The coach could not read this sentence. You can keep going and check it later.',
                  )}
                </ErrorLine>
              )}

              <div className="mt-5 flex items-center gap-4">
                <Button
                  onClick={feedback ? () => void next() : () => void checkIt()}
                  disabled={checking || !text.trim()}
                >
                  {checking
                    ? 'Checking…'
                    : feedback
                      ? i + 1 < task.steps.length
                        ? 'Next sentence'
                        : 'Finish'
                      : 'Check'}
                </Button>
                <span className="text-ghost text-[11px]">press Enter</span>
              </div>
            </>
          )}

          {finishing && (
            <Waiting since={finishSince}>The coach is reading your whole reply…</Waiting>
          )}

          {/* The close failed. The sentences are still here, and Try again
              sends them as they are — this is not the setup talking. */}
          {finishError !== null && !finishing && (
            <ErrorLine onRetry={() => void finish(done)}>
              {describeError(
                finishError,
                'Your reply is written, but the coach could not close and correct it.',
              )}
            </ErrorLine>
          )}
        </motion.div>
      </AnimatePresence>

      {/* What he has written so far, growing into a paragraph */}
      {done.length > 0 && (
        <div className="border-rule mt-6 border-t pt-4">
          <p className="text-ghost text-[10px] font-semibold tracking-[0.2em] uppercase">
            Your reply so far
          </p>
          <p className="font-book text-ink-soft mt-2 max-w-[62ch] text-[15px] leading-relaxed">
            {done.map((s) => (s.checked && s.fixed) || s.text).join(' ')}
          </p>
        </div>
      )}
    </section>
  )
}
