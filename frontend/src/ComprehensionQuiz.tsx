import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { api } from './api'
import type { Question } from './api'
import { Section, Choice, SLIDE, fmt } from './ui'
import type { ChoiceState } from './ui'

const LETTERS = ['A', 'B', 'C']

/* One quiz, two homes (Reader and Podcast). Answers are sent as soon as the
   last one is picked: comprehension is the low-effort evidence that keeps the
   assessment alive on days without writing (ADR-008 D2), and until M12 it was
   answered and then thrown away. */
export default function ComprehensionQuiz({
  textId,
  questions,
  title = 'Comprehension',
}: {
  textId: number
  questions: Question[]
  title?: string
}) {
  const [answers, setAnswers] = useState<(number | null)[]>(() =>
    questions.map(() => null),
  )
  const [saved, setSaved] = useState<{ score: number; total: number } | null>(null)

  function pick(qi: number, oi: number) {
    if (answers[qi] != null) return
    const next = answers.map((a, i) => (i === qi ? oi : a))
    setAnswers(next)
    if (next.every((a) => a != null)) {
      api
        .submitQuiz(textId, next as number[])
        .then(setSaved)
        .catch(() => undefined)
    }
  }

  return (
    <Section
      label={title}
      right={
        saved && (
          <span className="tnum">
            {fmt(saved.score)} / {fmt(saved.total)} · saved to your record
          </span>
        )
      }
    >
      <ol className="space-y-6">
        {questions.map((q, qi) => {
          const picked = answers[qi]
          const revealed = picked != null
          return (
            <li key={qi} className="max-w-[68ch]">
              <p className="font-book text-[15px] font-semibold">
                <span className="tnum text-ghost mr-2">{qi + 1}.</span>
                {q.question ?? q.prompt}
              </p>
              <div
                className="mt-2 space-y-1.5"
                role="radiogroup"
                aria-label={`Question ${qi + 1}`}
              >
                {q.options.map((opt, oi) => {
                  const chosen = picked === oi
                  const correct = oi === q.answer_index
                  const state: ChoiceState = !revealed
                    ? 'idle'
                    : correct
                      ? 'correct'
                      : chosen
                        ? 'wrong'
                        : 'muted'
                  return (
                    <Choice
                      key={oi}
                      letter={LETTERS[oi]}
                      state={state}
                      role="radio"
                      aria-checked={chosen}
                      onClick={() => pick(qi, oi)}
                      disabled={revealed}
                    >
                      {opt}
                    </Choice>
                  )
                })}
              </div>
              <AnimatePresence>
                {revealed && (
                  <motion.p
                    initial={{ y: -8, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={SLIDE}
                    className={`font-book mt-2 text-[13px] italic ${
                      picked === q.answer_index ? 'text-cobalt-deep' : 'text-correction'
                    }`}
                  >
                    {picked === q.answer_index
                      ? 'Correct — '
                      : `${LETTERS[q.answer_index]}. `}
                    {q.why}
                  </motion.p>
                )}
              </AnimatePresence>
            </li>
          )
        })}
      </ol>
    </Section>
  )
}
