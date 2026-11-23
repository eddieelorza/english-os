import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { BaselineLatest, DictationItem, DictationResult, VocabResult } from './api'
import { PlayButton } from './Audio'
import { Button, ErrorLine, Page, PageHeader, RuledSkeleton, Section, Waiting, describeError, fmt } from './ui'

/* Two short tests graded without a model (ADR-018). The numbers are an
   estimate with low confidence: the copy never calls them a level. */

type Mode = 'home' | 'vocab' | 'dictation'

const BAND_NAMES = ['Most common 1,000', '1–2k', '2–4k', '4–7k', '7–10k']
const pct = (n: number) => `${Math.round(n * 100)}%`
const day = (iso?: string) => (iso ? new Date(iso).toLocaleDateString() : '')
const message = (e: unknown, fallback: string) =>
  describeError(e instanceof Error ? e.message : null, fallback)

export default function CheckInPage() {
  const [mode, setMode] = useState<Mode>('home')
  const [latest, setLatest] = useState<BaselineLatest | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api.baseline().then(setLatest).catch((e: unknown) => setError(message(e, 'The check-in could not be opened.')))
  }, [])
  useEffect(load, [load])

  function back() {
    setMode('home')
    setError(null)
    load()
  }

  return (
    <Page>
      <PageHeader title="Check-in" subtitle="Two short tests, no AI. An estimate of where you are, not a certificate." />
      {mode === 'vocab' && <VocabTest onBack={back} />}
      {mode === 'dictation' && <DictationTest onBack={back} />}
      {mode === 'home' && (
        error ? <ErrorLine onRetry={() => { setError(null); load() }}>{error}</ErrorLine>
        : !latest ? <RuledSkeleton lines={2} />
        : (
          <ol className="border-rule mt-8 border-t">
            <TestRow
              title="Vocabulary"
              what="Do you know this word? Some are invented. About 5 minutes."
              last={latest.vocab && `~${fmt(latest.vocab.size)} words · ${latest.vocab.cefr} · ${latest.vocab.confidence} confidence · ${day(latest.vocab.taken_at)}`}
              onStart={() => setMode('vocab')}
            />
            <TestRow
              title="Dictation"
              what="Hear a sentence, type it. About 6 minutes."
              last={latest.dictation && `Heard up to ${latest.dictation.band} · ${pct(latest.dictation.accuracy)} of words · ${day(latest.dictation.taken_at)}`}
              onStart={() => setMode('dictation')}
            />
          </ol>
        )
      )}
    </Page>
  )
}

function TestRow({ title, what, last, onStart }: { title: string; what: string; last: string | null; onStart: () => void }) {
  return (
    <li className="border-rule flex flex-wrap items-center justify-between gap-4 border-b py-5">
      <div className="min-w-0">
        <h3 className="font-book text-xl font-semibold">{title}</h3>
        <p className="text-ink-soft mt-1 text-sm">{what}</p>
        <p className="tnum text-ghost mt-1 text-sm">{last ?? 'Not taken yet'}</p>
      </div>
      <Button type="button" onClick={onStart}>{last ? 'Take it again' : 'Take it'}</Button>
    </li>
  )
}

function BackLink({ onBack }: { onBack: () => void }) {
  return (
    <Button type="button" variant="text" tone="cobalt" onClick={onBack} className="mt-8">
      Back to Check-in
    </Button>
  )
}

/* ── Vocabulary yes/no ─────────────────────────────────────────────────── */

function VocabTest({ onBack }: { onBack: () => void }) {
  const [items, setItems] = useState<string[] | null>(null)
  const [answers, setAnswers] = useState<Record<string, boolean>>({})
  const [started, setStarted] = useState(false)
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState<VocabResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const word = useRef<HTMLParagraphElement>(null)

  const load = useCallback(() => {
    api.baselineVocabItems().then((r) => setItems(r.items)).catch((e: unknown) => setError(message(e, 'The words could not be loaded.')))
  }, [])
  useEffect(load, [load])

  const done = Object.keys(answers).length
  const current = items && started && done < items.length ? items[done] : null

  const submit = useCallback((all: Record<string, boolean>) => {
    setSending(true)
    setError(null)
    api.baselineVocab(all)
      .then(setResult)
      .catch((e: unknown) => setError(message(e, 'Your answers could not be saved. Try again.')))
      .finally(() => setSending(false))
  }, [])

  const answer = useCallback((known: boolean) => {
    if (!items || !current) return
    const next = { ...answers, [current]: known }
    setAnswers(next)
    if (Object.keys(next).length === items.length) submit(next)
  }, [answers, current, items, submit])

  useEffect(() => {
    if (!current) return
    word.current?.focus()
    function onKey(event: KeyboardEvent) {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return
      if (event.metaKey || event.ctrlKey || event.altKey || event.repeat) return
      const k = event.key.toLowerCase()
      if (k === 'y' || k === 'arrowleft') answer(true)
      else if (k === 'n' || k === 'arrowright') answer(false)
      else return
      event.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [current, answer])

  if (result) return <VocabResultView result={result} onBack={onBack} />
  if (error) return (
    <>
      <ErrorLine onRetry={items && done === items.length ? () => submit(answers) : () => { setError(null); load() }}>{error}</ErrorLine>
      <BackLink onBack={onBack} />
    </>
  )
  if (!items) return <RuledSkeleton lines={2} />
  if (sending) return <Waiting>Counting your answers…</Waiting>

  if (!started) return (
    <Section label="Vocabulary">
      <p className="font-book max-w-prose text-lg leading-relaxed">
        {fmt(items.length)} words, one at a time. Some of these words don't exist. Only say yes if you know what it means.
      </p>
      <p className="text-ghost mt-2 text-sm pointer-coarse:hidden">Keys: Y or ← for yes, N or → for no.</p>
      <Button type="button" className="mt-6" onClick={() => setStarted(true)} autoFocus>Begin</Button>
    </Section>
  )

  return (
    <Section label="Vocabulary" right={<span className="tnum">{fmt(done + 1)} of {fmt(items.length)}</span>}>
      <p ref={word} tabIndex={-1} aria-live="polite" className="font-book text-cobalt-deep py-8 text-center text-5xl outline-none">
        {current}
      </p>
      <div className="flex flex-wrap justify-center gap-4">
        <Button type="button" onClick={() => answer(true)}>Yes, I know it</Button>
        <Button type="button" variant="secondary" onClick={() => answer(false)}>No</Button>
      </div>
    </Section>
  )
}

function VocabResultView({ result, onBack }: { result: VocabResult; onBack: () => void }) {
  const invented = Math.round(result.false_alarms * 20)
  return (
    <Section label="Vocabulary">
      <div role="status" tabIndex={-1} ref={(el) => el?.focus()} className="outline-none">
        <p className="font-book tnum text-5xl font-semibold">About {fmt(result.size)} words</p>
        <p className="text-ink-soft mt-2">{result.cefr} · {result.confidence} confidence</p>
        {invented > 0 && (
          <p className="font-book text-correction mt-3 italic">
            You said yes to {fmt(invented)} invented {invented === 1 ? 'word' : 'words'} — that lowers the estimate.
          </p>
        )}
      </div>
      <dl className="border-rule mt-6 border-t">
        {result.bands.map((b) => (
          <div key={b.band} className="border-rule tnum flex justify-between border-b py-2 text-sm">
            <dt>{BAND_NAMES[b.band - 1] ?? `Band ${b.band}`}</dt>
            <dd className="text-ink-soft">{pct(b.known)}</dd>
          </div>
        ))}
      </dl>
      <BackLink onBack={onBack} />
    </Section>
  )
}

/* ── Dictation ─────────────────────────────────────────────────────────── */

const MAX_PLAYS = 2

function DictationTest({ onBack }: { onBack: () => void }) {
  const [items, setItems] = useState<DictationItem[] | null>(null)
  const [since, setSince] = useState<number | null>(() => Date.now())
  const [responses, setResponses] = useState<string[]>([])
  const [text, setText] = useState('')
  const [plays, setPlays] = useState(0)
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState<DictationResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)

  const load = useCallback(() => {
    api.baselineDictationItems()
      .then((r) => setItems(r.items))
      .catch((e: unknown) => setError(message(e, 'The audio could not be prepared.')))
      .finally(() => setSince(null))
  }, [])
  useEffect(load, [load])

  const submit = useCallback((all: string[]) => {
    setSending(true)
    setError(null)
    api.baselineDictation(all)
      .then(setResult)
      .catch((e: unknown) => setError(message(e, 'Your answers could not be saved. Try again.')))
      .finally(() => setSending(false))
  }, [])

  const index = responses.length
  const item = items && index < items.length ? items[index] : null

  useEffect(() => {
    if (item) input.current?.focus()
  }, [item])

  function next() {
    if (!items || !item) return
    const all = [...responses, text.trim()]
    setResponses(all)
    setText('')
    setPlays(0)
    if (all.length === items.length) submit(all)
  }

  if (result) return <DictationResultView result={result} onBack={onBack} />
  if (error) return (
    <>
      <ErrorLine onRetry={items && index === items.length ? () => submit(responses) : () => { setError(null); setSince(Date.now()); load() }}>{error}</ErrorLine>
      <BackLink onBack={onBack} />
    </>
  )
  if (!items) return <Waiting since={since}>Preparing the audio…</Waiting>
  if (sending || !item) return <Waiting>Checking what you heard…</Waiting>

  return (
    <Section label="Dictation" right={<span className="tnum">{fmt(index + 1)} of {fmt(items.length)}</span>}>
      <div className="flex items-center gap-3">
        <PlayButton
          key={item.id}
          src={item.audio}
          label={plays >= MAX_PLAYS ? 'Played twice' : 'Play the sentence'}
          size={28}
          disabled={plays >= MAX_PLAYS}
          onPlay={() => {
            setPlays((n) => n + 1)
            // Listen and type without reaching for the box; the button may disable.
            input.current?.focus()
          }}
        />
        <span className="tnum text-ghost text-sm">
          {plays >= MAX_PLAYS ? 'Played twice' : `${MAX_PLAYS - plays} ${MAX_PLAYS - plays === 1 ? 'play' : 'plays'} left`}
        </span>
      </div>
      <form className="mt-6" onSubmit={(e) => { e.preventDefault(); next() }}>
        <label className="block text-sm">
          What you heard
          <input
            ref={input}
            type="text"
            autoCapitalize="off"
            autoCorrect="off"
            autoComplete="off"
            spellCheck={false}
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="font-book border-rule-strong mt-2 block w-full border-b bg-transparent py-2 text-xl"
          />
        </label>
        <Button type="submit" className="mt-6">{index + 1 === items.length ? 'Finish' : 'Next'}</Button>
        <p className="text-ghost pointer-coarse:hidden mt-3 text-xs">Press Enter for the next sentence</p>
      </form>
    </Section>
  )
}

function DictationResultView({ result, onBack }: { result: DictationResult; onBack: () => void }) {
  return (
    <Section label="Dictation">
      <div role="status" tabIndex={-1} ref={(el) => el?.focus()} className="outline-none">
        <p className="font-book text-5xl font-semibold">Heard up to {result.band}</p>
        <p className="tnum text-ink-soft mt-2">{pct(result.accuracy)} of words · {result.confidence} confidence</p>
      </div>
      <ol className="border-rule mt-6 border-t">
        {result.items.map((it, i) => (
          <li key={i} className="border-rule border-b py-3">
            <div className="flex items-baseline justify-between gap-4">
              <p className="font-book">{it.expected}</p>
              <span className="tnum text-ghost shrink-0 text-sm">{it.level} · {pct(it.accuracy)}</span>
            </div>
            <p className={`font-book mt-1 text-sm ${it.accuracy < 1 ? 'text-correction' : 'text-ink-soft'}`}>
              {it.given || <span className="italic">(blank)</span>}
            </p>
          </li>
        ))}
      </ol>
      <BackLink onBack={onBack} />
    </Section>
  )
}
