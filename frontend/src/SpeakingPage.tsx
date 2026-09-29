import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { api } from './api'
import type { SpeakingResult } from './api'
import {
  Button,
  ErrorLine,
  Page,
  PageHeader,
  RuledSkeleton,
  SLIDE,
  Section,
  Waiting,
  describeError,
  fmt,
  useJobWatch,
} from './ui'
import ConversationPanel from './ConversationPanel'
import ChatGPTPrompt from './ChatGPTPrompt'

type Phase = 'idle' | 'recording' | 'recorded' | 'sending' | 'done'

/* Lesson 05: say it out loud. The coach asks, you answer, the correction
   becomes study material — same loop as writing, spoken. */
export default function SpeakingPage() {
  const [mode, setMode] = useState<'conversation' | 'monologue'>('conversation')
  const [prompt, setPrompt] = useState<string | null>(null)
  const [promptWords, setPromptWords] = useState<string[]>([])
  const [promptError, setPromptError] = useState<string | null>(null)
  const [promptSince, setPromptSince] = useState<number | null>(null)
  const [sendSince, setSendSince] = useState<number | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [seconds, setSeconds] = useState(0)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [result, setResult] = useState<SpeakingResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [micError, setMicError] = useState<string | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const blobRef = useRef<Blob | null>(null)
  const timerRef = useRef<number | undefined>(undefined)

  /* Speaking does not queue its own work, but it shares the one model with
     whatever the queue is chewing on — the day's writing task above all. When
     that is in flight, say so instead of letting a 60 s wait look like a hang. */
  const { job: taskJob, pending: taskPending } = useJobWatch(['writing_task'])
  const busy = taskJob?.status === 'queued' || taskJob?.status === 'running'
  const busyNote = busy
    ? taskPending > 1
      ? `The coach is busy with today's material — ${taskPending} things queued. One at a time keeps the laptop cool.`
      : "The coach is busy writing today's material, so this is slower than usual."
    : undefined

  function loadPrompt() {
    setPrompt(null)
    setPromptError(null)
    setPromptSince(Date.now())
    api
      .speakingPrompt()
      .then((p) => {
        setPrompt(p.prompt)
        setPromptWords(p.learning_words)
        setPromptSince(null)
      })
      .catch((e: unknown) => {
        setPromptSince(null)
        setPromptError(e instanceof Error ? e.message : String(e))
      })
  }

  useEffect(() => () => window.clearInterval(timerRef.current), [])

  /* El tema del monólogo lo escribe un modelo: pedirlo sólo al abrir esa
     pestaña. Pedirlo al entrar a Speaking cargaba Ollama (5 GB) aunque fueras
     a conversar o a copiar el prompt de ChatGPT. */
  const asked = useRef(false)
  useEffect(() => {
    if (mode !== 'monologue' || asked.current) return
    asked.current = true
    loadPrompt()
  }, [mode])

  async function startRecording() {
    setError(null)
    setMicError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const rec = new MediaRecorder(stream)
      chunksRef.current = []
      rec.ondataavailable = (e) => chunksRef.current.push(e.data)
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || 'audio/webm' })
        blobRef.current = blob
        setAudioUrl(URL.createObjectURL(blob))
        setPhase('recorded')
      }
      rec.start()
      recorderRef.current = rec
      setSeconds(0)
      setPhase('recording')
      timerRef.current = window.setInterval(() => setSeconds((s) => s + 1), 1000)
    } catch (e: unknown) {
      setMicError(e instanceof Error ? e.message : String(e))
    }
  }

  function stopRecording() {
    window.clearInterval(timerRef.current)
    recorderRef.current?.stop()
  }

  async function send() {
    if (!blobRef.current) return
    setPhase('sending')
    setError(null)
    setSendSince(Date.now())
    try {
      const r = await api.speakingSubmit(blobRef.current, prompt ?? '')
      setResult(r)
      setPhase('done')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
      setPhase('recorded')
    } finally {
      setSendSince(null)
    }
  }

  function reset() {
    setPhase('idle')
    setResult(null)
    setAudioUrl(null)
    blobRef.current = null
    loadPrompt()
  }

  return (
    <Page width="study">
      <PageHeader title="Speaking" />
      <ChatGPTPrompt mode="speaking" />

      {/* Dos ejercicios distintos, una sola pestaña: la barra de navegación ya
          se desborda a 800 px y una décima entrada la rompía. Conversación
          por defecto — es lo que se hace casi siempre; el monólogo sigue
          disponible porque ya se usaba. */}
      <div className="border-rule mt-6 flex gap-6 border-b pb-3">
        {(['conversation', 'monologue'] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`text-[11px] font-semibold tracking-[0.16em] uppercase transition-colors ${
              mode === m
                ? 'text-cobalt-deep border-cobalt-deep -mb-[13px] border-b-2 pb-3'
                : 'text-ghost hover:text-ink-soft'
            }`}
          >
            {m === 'conversation' ? 'Conversación' : 'Monólogo'}
          </button>
        ))}
      </div>

      {mode === 'conversation' && <ConversationPanel />}

      {mode === 'monologue' && (
        <>
      {/* The coach's question */}
      <Section
        label="The coach asks"
        right={
          phase === 'idle' && (
            <Button variant="text" size="sm" onClick={loadPrompt}>
              Another question
            </Button>
          )
        }
      >
        {promptError !== null ? (
          <ErrorLine onRetry={loadPrompt}>
            {describeError(promptError, 'The coach could not think of a question to ask you.')}
          </ErrorLine>
        ) : prompt ? (
          <>
            <p className="font-book mt-3 text-2xl leading-snug">{prompt}</p>
            {promptWords.length > 0 && (
              <p className="text-ghost mt-2 text-[12px]">
                Try to use:{' '}
                {promptWords.map((w, i) => (
                  <span key={w}>
                    {i > 0 && ' · '}
                    <span className="text-cobalt-deep font-semibold">{w}</span>
                  </span>
                ))}
              </p>
            )}
          </>
        ) : (
          <>
            <Waiting since={promptSince} note={busyNote}>
              The coach is thinking of a question…
            </Waiting>
            <RuledSkeleton lines={2} />
          </>
        )}
      </Section>

      {/* Record controls */}
      <Section>
        {phase === 'idle' && (
          <Button onClick={startRecording} disabled={!prompt}>
            Start speaking
          </Button>
        )}

        {micError !== null && (
          <ErrorLine onRetry={startRecording} retryLabel="Try the microphone again">
            {describeError(
              micError,
              'The microphone could not be opened — check the browser permission.',
            )}
          </ErrorLine>
        )}

        {phase === 'recording' && (
          <div className="flex items-center gap-5">
            <Button variant="danger" onClick={stopRecording}>
              Stop
            </Button>
            <p className="tnum text-ink-soft text-[14px]">
              <span aria-hidden className="bg-correction mr-2 inline-block h-2 w-2 animate-pulse rounded-full" />
              Recording · {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, '0')}
            </p>
          </div>
        )}

        {(phase === 'recorded' || phase === 'sending') && audioUrl && (
          <div className="flex flex-wrap items-center gap-5">
            <audio controls src={audioUrl} className="h-9" />
            <Button onClick={send} disabled={phase === 'sending'}>
              {phase === 'sending' ? 'The coach is listening…' : 'Send to the coach'}
            </Button>
            {phase !== 'sending' && (
              <Button variant="text" onClick={reset}>
                Discard
              </Button>
            )}
          </div>
        )}

        {phase === 'sending' && (
          <Waiting since={sendSince} note={busyNote}>
            The coach is listening to your answer…
          </Waiting>
        )}

        {error !== null && phase !== 'sending' && (
          <ErrorLine onRetry={send}>
            {describeError(error, 'The coach could not process the recording.')}
          </ErrorLine>
        )}
      </Section>

      {/* The correction */}
      <AnimatePresence>
        {phase === 'done' && result && (
          <motion.div
            initial={{ y: 16, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={SLIDE}
          >
            <Section label="What you said">
              <p className="font-book text-ink-soft mt-2 max-w-[68ch] text-[15px] leading-relaxed italic">
                “{result.transcript}”
              </p>
              <p className="tnum text-ghost mt-1 text-[12px]">
                {fmt(result.words_produced)} words · {Math.round(result.duration_seconds)} s
              </p>

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
                How a fluent speaker would say it
              </h3>
              <p className="font-book mt-2 max-w-[68ch] text-[16px] leading-relaxed">
                {result.natural_version}
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

              <p className="text-ghost mt-4 text-[12px]">
                {result.errors.length > 0
                  ? `${result.errors.length} correction${result.errors.length === 1 ? '' : 's'} saved to your error library — tomorrow's material will target them.`
                  : 'No errors recorded — clean answer.'}
              </p>

              <Button onClick={reset} className="mt-6">
                Speak again
              </Button>
            </Section>
          </motion.div>
        )}
      </AnimatePresence>
        </>
      )}
    </Page>
  )
}
