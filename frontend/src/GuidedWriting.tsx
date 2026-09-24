import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { api } from './api'
import type { GuidedResult, WritingTask, WrittenSentence } from './api'
import { Button, ErrorLine, RuledSkeleton, SLIDE, fmt } from './ui'

/* Writing, one sentence at a time.
   The evidence behind this shape: three writing sessions in the whole project.
   "Four to six sentences" sounds small but is still an empty box, and an empty
   box is the wall. The one time the writing flowed it was a letter to a person
   ("Hi Arnold…", 77 words) — so: a real recipient, one sentence at a time, and
   the correction right there, which is the Practice drill's shape and the one
   that gets used. */
export default function GuidedWriting({
  onDone,
}: {
  onDone: (r: GuidedResult) => void
}) {
  const [task, setTask] = useState<WritingTask | null>(null)
  const [failed, setFailed] = useState(false)
  const [i, setI] = useState(0)
  const [text, setText] = useState('')
  const [checking, setChecking] = useState(false)
  const [done, setDone] = useState<WrittenSentence[]>([])
  const [feedback, setFeedback] = useState<WrittenSentence | null>(null)
  const [seconds, setSeconds] = useState(0)
  const timer = useRef<number | undefined>(undefined)
  const box = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.writingSteps().then(setTask).catch(() => setFailed(true))
    return () => window.clearInterval(timer.current)
  }, [])

  const step = task?.steps[i]

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
    try {
      const r = await api.writingCheck(text.trim(), step.ask)
      setFeedback({ ...r, text: text.trim() })
    } catch {
      // Never strand him mid-sentence over a model hiccup: keep what he wrote.
      setFeedback({ ok: true, fixed: text.trim(), note: '', text: text.trim() })
    } finally {
      setChecking(false)
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
    try {
      onDone(await api.writingFinish(all, task.scenario, seconds))
    } catch {
      setFailed(true)
    }
  }

  if (failed)
    return (
      <ErrorLine>
        The coach could not set up today's message. Check the AI setup, or write
        freely below.
      </ErrorLine>
    )

  if (!task) return <RuledSkeleton lines={3} />

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

      {/* One segment per sentence, filled as you go */}
      <div className="mt-6 flex gap-[3px]" aria-hidden>
        {task.steps.map((_, n) => (
          <span
            key={n}
            className={`h-[3px] flex-1 rounded-full transition-colors duration-300 ${
              n < done.length
                ? done[n].ok
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
                feedback ? next() : checkIt()
              }
            }}
            className="font-book border-rule focus:border-cobalt mt-4 w-full border-b bg-transparent pb-2 text-[19px] outline-none disabled:opacity-70"
          />

          <AnimatePresence>
            {feedback && (
              <motion.div
                initial={{ y: -6, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={SLIDE}
                className={`mt-4 border-l-2 py-1 pl-3 ${
                  feedback.ok ? 'border-cobalt/40' : 'border-correction/40'
                }`}
              >
                <p
                  className={`text-[10px] font-semibold tracking-[0.2em] uppercase ${
                    feedback.ok ? 'text-cobalt-deep' : 'text-correction'
                  }`}
                >
                  {feedback.ok ? 'Right as it is' : 'Almost'}
                </p>
                {!feedback.ok && (
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

          <div className="mt-5 flex items-center gap-4">
            <Button onClick={feedback ? next : checkIt} disabled={checking || !text.trim()}>
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
        </motion.div>
      </AnimatePresence>

      {/* What he has written so far, growing into a paragraph */}
      {done.length > 0 && (
        <div className="border-rule mt-6 border-t pt-4">
          <p className="text-ghost text-[10px] font-semibold tracking-[0.2em] uppercase">
            Your reply so far
          </p>
          <p className="font-book text-ink-soft mt-2 max-w-[62ch] text-[15px] leading-relaxed">
            {done.map((s) => s.fixed || s.text).join(' ')}
          </p>
        </div>
      )}
    </section>
  )
}
