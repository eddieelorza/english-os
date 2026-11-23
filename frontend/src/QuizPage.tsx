import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { QuizNext } from './api'
import SessionNext from './SessionNext'
import { Button, Empty, ErrorLine, Page, PageHeader, RuledSkeleton, Section, Waiting, describeError, fmt } from './ui'

/* The delayed test of experiments E1/E2 (ADR-018). It does not touch the
   review schedule and shows no answer: seeing it at day 7 would spoil the
   day-30 check of the same word. */
export default function QuizPage() {
  const [next, setNext] = useState<QuizNext | null>(null)
  const [answer, setAnswer] = useState('')
  const [count, setCount] = useState(0)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)

  const load = useCallback(() => {
    api.quiz().then(setNext).catch((e: unknown) =>
      setError(describeError(e instanceof Error ? e.message : null, 'The quiz could not be loaded.')))
  }, [])
  useEffect(load, [load])

  const item = next?.item
  useEffect(() => {
    if (item && !sending) input.current?.focus()
  }, [item, sending])

  function submit(given: string) {
    if (!item || sending) return
    setSending(true)
    setError(null)
    api.quizAnswer(item.probe_id, given)
      .then((r) => {
        setNext(r)
        setAnswer('')
        setCount((n) => n + 1)
      })
      .catch((e: unknown) =>
        setError(describeError(e instanceof Error ? e.message : null, 'Your answer could not be saved. Try again.')))
      .finally(() => setSending(false))
  }

  return (
    <Page>
      <PageHeader
        title="Quiz"
        subtitle="A few words from days ago. It doesn't change your reviews, and answers stay hidden so the next check is fair."
      />
      {error && <ErrorLine onRetry={item ? () => submit(answer) : () => { setError(null); load() }}>{error}</ErrorLine>}
      {!next && !error && <RuledSkeleton lines={2} />}
      {next && !item && (
        <div role="status">
          <Empty hint={count ? `${fmt(count)} answered — saved for the experiments.` : undefined}>
            No surprise questions left today.
          </Empty>
          <SessionNext after="quiz" />
        </div>
      )}
      {item && (
        <Section label="Quiz" right={<span className="tnum">{fmt(next.left)} left</span>}>
          <p className="font-book text-2xl leading-relaxed">
            {item.sentence.split(/(____)/).map((part, i) => part === '____' ? (
              <span key={i} aria-label="blank" className="border-cobalt text-cobalt-deep border-b-2 px-2">____</span>
            ) : part)}
          </p>
          <p className="tnum text-ghost mt-3 text-sm">
            {item.hint.replace(/^(.+)\s*·\s*(\d+)$/, (_, letter: string, n: string) => `${letter.trim()} · ${n} letters`)}
          </p>
          <form className="mt-6" onSubmit={(e) => { e.preventDefault(); submit(answer) }}>
            <label className="block text-sm">
              The missing word
              <input
                ref={input}
                type="text"
                autoCapitalize="off"
                autoCorrect="off"
                autoComplete="off"
                spellCheck={false}
                value={answer}
                disabled={sending}
                onChange={(e) => setAnswer(e.target.value)}
                className="font-book border-rule-strong mt-2 block w-full border-b bg-transparent py-2 text-xl"
              />
            </label>
            <div className="mt-6 flex flex-wrap items-center gap-4">
              <Button type="submit" disabled={sending}>Next</Button>
              <Button type="button" variant="text" disabled={sending} onClick={() => submit('')}>I don't know</Button>
            </div>
          </form>
          {sending && <Waiting>Saving…</Waiting>}
        </Section>
      )}
    </Page>
  )
}
