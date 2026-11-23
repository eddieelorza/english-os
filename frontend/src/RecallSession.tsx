import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { api } from './api'
import type { RecallNext, RecallResult } from './api'
import { mediaUrl, PlayButton } from './Audio'
import SessionNext from './SessionNext'
import { Page, PageHeader, Section, Button, ErrorLine, Waiting, Empty, describeError, fmt } from './ui'

/* Its own page, so "Continue — Recall" on Today never lands on a Review card
   still in its learning steps. Here the sitting starts at once. */
export function RecallPage() {
  return (
    <Page>
      <PageHeader title="Recall" subtitle="See the meaning or the gap, type the English word." />
      <RecallSession autoStart />
    </Page>
  )
}

/* Availability and the sitting live together so Review only needs mount points. */
export default function RecallSession({ autoStart = false }: { autoStart?: boolean }) {
  const [next, setNext] = useState<RecallNext | null>(null)
  const [started, setStarted] = useState(autoStart)
  const [answered, setAnswered] = useState(0)
  const [answer, setAnswer] = useState('')
  const [result, setResult] = useState<RecallResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [answerError, setAnswerError] = useState<string | null>(null)
  const live = useRef(true)
  const requestId = useRef(0)
  const locked = useRef(false)
  const failedAnswer = useRef('')
  const input = useRef<HTMLInputElement>(null)
  const continueControls = useRef<HTMLDivElement>(null)
  const ending = useRef<HTMLDivElement>(null)
  const instructionId = useId()

  const load = useCallback(() => {
    const id = ++requestId.current
    return api.recallNext()
      .then((response) => {
        if (!live.current || id !== requestId.current) return
        setNext(response)
        setResult(null)
        setAnswer('')
        setAnswerError(null)
      })
      .catch((error: unknown) => {
        if (live.current && id === requestId.current) {
          const message = error instanceof Error ? error.message : null
          setLoadError(describeError(message, message || 'The next word could not be loaded. Try again.'))
        }
      })
      .finally(() => {
        if (live.current && id === requestId.current) setLoading(false)
      })
  }, [])

  useEffect(() => {
    live.current = true
    void load()
    return () => {
      live.current = false
    }
  }, [load])

  useEffect(() => {
    if (!started || loading || submitting) return
    if (result) continueControls.current?.querySelector('button')?.focus()
    else if (next?.item) input.current?.focus()
    else ending.current?.focus()
  }, [started, loading, submitting, loadError, next, result])

  useEffect(() => {
    if (!started) return
    // Keep the stopped review's window shortcuts dormant, including while a
    // disabled control loses focus. Native actions and React handlers still run.
    function containReviewKeys(event: KeyboardEvent) {
      if (['Enter', ' ', '1', '2', '3', '4'].includes(event.key)) event.stopPropagation()
    }
    document.addEventListener('keydown', containReviewKeys)
    return () => document.removeEventListener('keydown', containReviewKeys)
  }, [started])

  function loadNext() {
    if (loading) return
    setLoading(true)
    setLoadError(null)
    void load()
  }

  async function check(given: string) {
    if (!next?.item || result || loading || locked.current) return
    locked.current = true
    failedAnswer.current = given
    setSubmitting(true)
    setAnswerError(null)
    try {
      const response = await api.recallAnswer(next.item.word_id, next.item.exercise, given)
      if (!live.current) return
      setResult(response)
      setAnswered((count) => count + 1)
    } catch (error) {
      if (live.current) {
        const message = error instanceof Error ? error.message : null
        setAnswerError(describeError(message, message || 'Your answer could not be checked. Try again.'))
      }
    } finally {
      locked.current = false
      if (live.current) setSubmitting(false)
    }
  }

  const item = next?.item
  const available = (next?.due ?? 0) + (next?.new_left ?? 0)
  if (!started && !loadError && (!item || available <= 0)) return null

  return (
    <Section label="Recall" className="font-ui text-left">
      <div
        className="max-w-prose break-words"
        onKeyDown={(event) => {
          // A stopped review can still have a card and a window keyboard listener.
          event.stopPropagation()
          if (event.key === 'Enter' && (event.repeat || event.nativeEvent.isComposing)) {
            event.preventDefault()
          }
        }}
      >
        {!started && item && available > 0 && !loadError && (
          <div className="flex flex-wrap items-center gap-4">
            <p className="tnum text-ghost text-sm">{fmt(available)} words to recall</p>
            <Button type="button" onClick={() => setStarted(true)}>Start recall</Button>
          </div>
        )}

        {started && item && (
          <>
            <p className="tnum text-ghost mb-4 text-sm">
              Recall · {fmt(result ? answered : answered + 1)}
              {item.is_new && <span className="ml-3 border-b border-dashed border-rule-strong text-xs">new</span>}
            </p>

            {!result ? (
              <>
                {item.exercise === 'meaning' && (
                  <>
                    <p lang="es" className="font-book text-cobalt-deep text-3xl">{item.meaning_es}</p>
                    {item.definition_en && <p className="font-book text-ink-soft mt-3 text-lg">{item.definition_en}</p>}
                  </>
                )}
                {item.exercise === 'cloze' && (
                  <>
                    <p className="font-book text-2xl leading-relaxed">
                      {item.sentence?.split(/(____)/).map((part, index) => part === '____' ? (
                        <span key={index} aria-label="blank" className="border-cobalt text-cobalt-deep border-b-2 px-2">____</span>
                      ) : part)}
                    </p>
                    {item.hint && <p className="tnum text-ghost mt-3 text-sm">{item.hint.replace(/^(.+)\s*·\s*(\d+)$/, (_, letter: string, count: string) => `${letter.trim()} · ${count} letters`)}</p>}
                    {item.translation && <p lang="es" className="font-book text-ghost mt-3 text-lg italic">{item.translation}</p>}
                  </>
                )}
                {item.exercise === 'image' && (
                  <>
                    {item.image && <img src={mediaUrl(item.image)} alt={item.definition_en ?? ''} className="max-h-64 max-w-full object-contain" />}
                    {item.definition_en && <p className="font-book mt-3 text-xl">{item.definition_en}</p>}
                  </>
                )}

                <p id={instructionId} className="text-ink-soft mt-6 text-sm">
                  {item.exercise === 'meaning' ? 'Type the English word.' : item.exercise === 'cloze' ? 'Type the missing word.' : 'Type the word for this picture.'}
                </p>
                <form className="mt-4" onSubmit={(event) => { event.preventDefault(); void check(answer) }}>
                  <label className="block text-sm">
                    Your answer
                    <input
                      ref={input}
                      type="text"
                      autoFocus
                      autoCapitalize="off"
                      autoCorrect="off"
                      autoComplete="off"
                      spellCheck={false}
                      aria-describedby={instructionId}
                      value={answer}
                      onChange={(event) => setAnswer(event.target.value)}
                      disabled={submitting || loading}
                      className="font-book border-rule-strong mt-2 block w-full border-b bg-transparent py-2 text-xl"
                    />
                  </label>
                  <div className="mt-6 flex flex-wrap items-center gap-4">
                    <Button type="submit" disabled={submitting || loading}>Check</Button>
                    <Button type="button" variant="text" disabled={submitting || loading} onClick={() => void check('')}>I don't know</Button>
                  </div>
                  <p className="text-ghost pointer-coarse:hidden mt-3 text-xs">Press Enter to check</p>
                </form>
                {submitting && <Waiting>Checking your answer…</Waiting>}
                {answerError && <ErrorLine onRetry={() => void check(failedAnswer.current)}>{answerError}</ErrorLine>}
              </>
            ) : (
              <>
                <div role="status" aria-atomic="true">
                  <p className="text-lg">
                    {result.verdict === 'correct' ? 'Correct.' : result.verdict === 'close' ? <>Almost — <span className="font-book">{result.expected}</span>.</> : <>It's <span className="font-book">{result.expected}</span>.</>}
                  </p>
                  {result.verdict === 'close' && result.given !== result.expected && (
                    <p className="text-ghost mt-2 text-sm">You typed: <s className="font-book text-lg">{result.given}</s></p>
                  )}
                  <p className="font-book mt-4 text-xl leading-relaxed">{highlightWord(result.example_en, result.word)}</p>
                  {result.example_es && <p lang="es" className="font-book text-ghost mt-2 text-lg italic">{result.example_es}</p>}
                  {result.image && <img src={mediaUrl(result.image)} alt={item.definition_en ?? ''} className="mt-4 max-h-64 max-w-full object-contain" />}
                  <p className="tnum text-ghost mt-4 text-sm">Next review in {result.interval}</p>
                </div>
                <div ref={continueControls} className="mt-6 flex flex-wrap items-center gap-4">
                  {/* Native Enter on the focused button has one path to load. */}
                  <Button type="button" disabled={loading} onClick={loadNext}>Continue</Button>
                  <PlayButton src={result.audio} label={`Hear ${result.word}`} size={22} />
                </div>
                <p className="text-ghost pointer-coarse:hidden mt-3 text-xs">Press Enter to continue</p>
              </>
            )}
          </>
        )}

        {loading && started && <Waiting>Loading the next word…</Waiting>}
        {loadError && <ErrorLine onRetry={loadNext}>{loadError}</ErrorLine>}
        {started && next && !item && !loading && !loadError && (
          <div ref={ending} tabIndex={-1} role="status">
            <Empty hint={`${fmt(answered)} ${answered === 1 ? 'word' : 'words'} answered this sitting.`}>Nothing left to recall today.</Empty>
            <SessionNext after="recall" />
          </div>
        )}
      </div>
    </Section>
  )
}

function highlightWord(sentence: string, word: string) {
  if (!word) return sentence
  // Same stem as the server's `surface`: "defeat" has to light up "defeated".
  const multi = /\s/.test(word.trim())
  const stem = multi ? word.trim() : word.slice(0, Math.max(3, word.length - 2))
  const escaped = stem.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const matches = new RegExp(`(?<![\\p{L}\\p{N}_])(${escaped}${multi ? '' : '\\p{L}*'})(?![\\p{L}\\p{N}_])`, 'giu')
  return sentence.split(matches).map((part, index) => index % 2 ? (
    <mark key={index} className="bg-cobalt-wash text-cobalt-deep font-semibold">{part}</mark>
  ) : part)
}
