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

/* A sentence kept during an outage is evidence of writing, not correctness.
   Carry that distinction through the draft and the finish call. */
type Feedback = WrittenSentence

const DRAFT_KEY = 'writing.guided.v1'

type GuidedDraft = {
  task: string
  i: number
  text: string
  done: Feedback[]
  feedback: Feedback | null
}

function taskIdentity(task: WritingTask) {
  return JSON.stringify([task.scenario, task.message, task.steps.map((s) => s.ask)])
}

function isFeedback(value: unknown): value is Feedback {
  if (value === null || typeof value !== 'object') return false
  const s = value as Partial<Feedback>
  return typeof s.text === 'string' && typeof s.checked === 'boolean' &&
    typeof s.ok === 'boolean' && typeof s.fixed === 'string' &&
    typeof s.note === 'string' && (s.category === undefined || typeof s.category === 'string')
}

function clearDraft() {
  try {
    localStorage.removeItem(DRAFT_KEY)
  } catch {
    /* Storage is optional; the current page still works. */
  }
}

function readDraft(task: WritingTask): GuidedDraft | null {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? 'null')
    if (saved !== null && typeof saved === 'object') {
      const d = saved as Partial<GuidedDraft>
      if (d.task === taskIdentity(task) && typeof d.text === 'string' &&
          Array.isArray(d.done) && d.done.every(isFeedback) &&
          d.done.length <= task.steps.length &&
          d.i === Math.min(d.done.length, task.steps.length - 1) &&
          (d.feedback === null || (isFeedback(d.feedback) &&
            d.done.length < task.steps.length && d.feedback.text === d.text.trim()))) {
        return d as GuidedDraft
      }
    }
  } catch {
    /* Ignore unavailable storage and malformed drafts. */
  }
  clearDraft()
  return null
}

function forServer(list: Feedback[]): WrittenSentence[] {
  return list.map(({ ok, fixed, note, category, text, checked }) => ({
    ok,
    fixed,
    note,
    category,
    text,
    checked,
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
  const loadId = useRef(0)

  const loadTask = useCallback(() => {
    const id = ++loadId.current
    setSetupError(null)
    setTask(null)
    setLoadingSince(Date.now())
    api
      .writingSteps()
      .then((t) => {
        if (id !== loadId.current) return
        const draft = readDraft(t)
        setDone(draft?.done ?? [])
        setI(draft?.i ?? 0)
        setText(draft?.text ?? (t.steps[0]?.starter ? `${t.steps[0].starter} ` : ''))
        setFeedback(draft?.feedback ?? null)
        setCheckError(draft?.feedback && !draft.feedback.checked ? 'Sentence not checked' : null)
        setTask(t)
        setLoadingSince(null)
      })
      .catch((e: unknown) => {
        if (id !== loadId.current) return
        setLoadingSince(null)
        setSetupError(e instanceof Error ? e.message : String(e))
      })
  }, [])

  useEffect(() => {
    loadTask()
    return () => {
      loadId.current += 1
      window.clearInterval(timer.current)
    }
  }, [loadTask])

  const step = task?.steps[i]
  /* Every sentence answered: the drill is over even if the close failed, so
     the box and the Check button go away instead of inviting a fifth
     sentence that would be sent twice. */
  const atEnd = task != null && done.length >= task.steps.length

  useEffect(() => {
    if (!task) return
    const starter = task.steps[0]?.starter ? `${task.steps[0].starter} ` : ''
    if (done.length === 0 && feedback === null && i === 0 && text === starter) {
      clearDraft()
      return
    }
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({ task: taskIdentity(task), i, text, done, feedback }))
    } catch {
      /* Keep writing even when storage is unavailable or full. */
    }
  }, [task, i, text, done, feedback])

  useEffect(() => {
    box.current?.focus()
  }, [step])

  function startOver() {
    if (!task || checking || finishing) return
    clearDraft()
    setDone([])
    setI(0)
    setText(task.steps[0]?.starter ? `${task.steps[0].starter} ` : '')
    setFeedback(null)
    setCheckError(null)
    setFinishError(null)
    window.clearInterval(timer.current)
    timer.current = undefined
    setSeconds(0)
  }

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
      const result = await api.writingFinish(forServer(all), task.scenario, seconds)
      clearDraft()
      onDone(result)
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
      const starter = task.steps[i + 1].starter
      setText(starter ? `${starter} ` : '')
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
        <p className="text-cobalt-deep text-xs font-semibold tracking-label uppercase">
          From {task.from_name}
        </p>
        <p className="font-book mt-2 max-w-[62ch] text-base leading-relaxed">
          {task.message}
        </p>
        <p lang="es" className="font-book text-ghost mt-2 text-sm italic">
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
              <p className="tnum text-ghost text-xs">
                Sentence {fmt(i + 1)} of {fmt(task.steps.length)}
              </p>
              <p lang="es" className="font-book mt-1 max-w-[58ch] text-lg font-semibold">
                {step?.ask}
              </p>
              {step?.word && (
                <p className="text-ghost mt-1 text-xs">
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
                className="font-book border-rule focus:border-cobalt mt-4 w-full border-b bg-transparent pb-2 text-lg outline-none disabled:opacity-70"
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
                      className={`text-xs font-semibold tracking-label uppercase ${
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
                      <p className="font-book text-cobalt-deep mt-1 text-base">
                        {feedback.fixed}
                      </p>
                    )}
                    {feedback.note && (
                      <p lang="es" className="font-book text-ink-soft mt-1 max-w-[58ch] text-sm italic">
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
                <span className="text-ghost text-xs">press Enter</span>
              </div>
            </>
          )}

          {finishing && (
            <Waiting since={finishSince}>The coach is reading your whole reply…</Waiting>
          )}

          {atEnd && !finishing && finishError === null && (
            <Button onClick={() => void finish(done)}>Finish</Button>
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
          <p className="text-ghost text-xs font-semibold tracking-label uppercase">
            Your reply so far
          </p>
          <p className="font-book text-ink-soft mt-2 max-w-[62ch] text-base leading-relaxed">
            {done.map((s) => (s.checked && s.fixed) || s.text).join(' ')}
          </p>
        </div>
      )}
      {(done.length > 0 || feedback !== null) && (
        <Button variant="text" onClick={startOver} disabled={checking || finishing} className="mt-6">
          Start over
        </Button>
      )}
    </section>
  )
}
