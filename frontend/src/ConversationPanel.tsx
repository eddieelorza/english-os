import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { api } from './api'
import { mediaUrl } from './Audio'
import type { ConversationSummary } from './api'
import { Button, ErrorLine, SLIDE, Section, Waiting, describeError } from './ui'

type Line = { who: 'you' | 'partner'; text: string; audio?: string | null }

/* Cada fallo dice qué pasó y qué botón lo deshace. Nada de "revisa el modelo
   en Reading": la causa se nombra aquí y el reintento está aquí. */
const ERROR_FALLBACK = {
  open: 'No pude abrir la conversación.',
  turn: 'Se cayó el turno, pero tu grabación sigue aquí.',
  silent: 'No se oyó nada. ¿El micrófono estaba mudo?',
  mic: 'No pude usar el micrófono. Dale permiso al navegador.',
  close: 'No pude cerrar la conversación. La charla sigue abierta.',
} as const

const RETRY_LABEL = {
  open: 'Intentar otra vez',
  turn: 'Reenviar lo que dijiste',
  silent: 'Grabar otra vez',
  mic: 'Probar el micrófono otra vez',
  close: 'Cerrar otra vez',
} as const
type Phase = 'idle' | 'opening' | 'ready' | 'recording' | 'thinking' | 'closing' | 'done'

/* Hablar con alguien, no responder a una pregunta.

   Dos cosas gobiernan esta pantalla:

   1. Un turno tarda ~5 s (transcribir + pensar + hablar). Sin un estado
      visible de "está pensando", la pantalla parece colgada y se pulsa dos
      veces. Por eso `thinking` es una fase con su propio texto.
   2. NO se corrige aquí. El compañero devuelve bien dicho lo que dijiste mal
      sin señalarlo; las correcciones sólo aparecen al cerrar, y como mucho
      tres. Pintar avisos durante la charla es exactamente lo abrumador que
      esta función existe para evitar. */
export default function ConversationPanel() {
  const [phase, setPhase] = useState<Phase>('idle')
  const [convId, setConvId] = useState<number | null>(null)
  const [lines, setLines] = useState<Line[]>([])
  const [summary, setSummary] = useState<ConversationSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  /* Un turno perdido se reintenta reenviando el audio; un turno mudo se
     reintenta hablando otra vez. Son dos salidas distintas. */
  const [errorKind, setErrorKind] = useState<'open' | 'turn' | 'silent' | 'mic' | 'close'>('turn')
  const [seconds, setSeconds] = useState(0)
  /* El reloj de la espera: un turno tarda ~5 s y el cierre bastante más. */
  const [waitSince, setWaitSince] = useState<number | null>(null)

  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  /* Lo último que se grabó, para poder reenviarlo si el turno se cae. */
  const lastBlobRef = useRef<Blob | null>(null)
  const timerRef = useRef<number | undefined>(undefined)
  const endRef = useRef<HTMLDivElement | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  useEffect(() => () => window.clearInterval(timerRef.current), [])

  /* Precalentar cuando el puntero o el foco llegan al botón, no al abrir la
     pestaña: Ollama son 5 GB de un Mac de 16 y abrir Speaking sólo para copiar
     el prompt de ChatGPT lo mandaba a swap. Cargar Ollama (4.3 s) y Kokoro
     (5.6 s) sigue adelantándose unos segundos al clic. Si falla, el primer
     turno sólo tarda más. */
  const warmed = useRef(false)
  const warm = () => {
    if (warmed.current) return
    warmed.current = true
    void api.conversationWarm().catch(() => undefined)
  }
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [lines, phase])

  /* El compañero habla solo: si hay que pulsar un botón para oírle, deja de
     parecer una conversación. */
  const speak = useCallback((path?: string | null) => {
    if (!path) return
    audioRef.current?.pause()
    const audio = new Audio(mediaUrl(path))
    audioRef.current = audio
    void audio.play().catch(() => undefined)
  }, [])

  async function begin() {
    setError(null)
    setPhase('opening')
    setWaitSince(Date.now())
    try {
      const r = await api.conversationStart()
      setConvId(r.conversation_id)
      setLines([{ who: 'partner', text: r.reply, audio: r.audio }])
      speak(r.audio)
      setPhase('ready')
    } catch (e: unknown) {
      setErrorKind('open')
      setError(e instanceof Error ? e.message : String(e))
      setPhase('idle')
    } finally {
      setWaitSince(null)
    }
  }

  async function startRecording() {
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const rec = new MediaRecorder(stream)
      chunksRef.current = []
      rec.ondataavailable = (e) => e.data.size && chunksRef.current.push(e.data)
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
        lastBlobRef.current = blob
        void send(blob)
      }
      recorderRef.current = rec
      rec.start()
      setSeconds(0)
      timerRef.current = window.setInterval(() => setSeconds((s) => s + 1), 1000)
      setPhase('recording')
    } catch (e: unknown) {
      setErrorKind('mic')
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  function stopRecording() {
    window.clearInterval(timerRef.current)
    recorderRef.current?.stop()
    setWaitSince(Date.now())
    setPhase('thinking')
  }

  async function send(blob: Blob) {
    if (convId == null) return
    setError(null)
    setPhase('thinking')
    setWaitSince((t) => t ?? Date.now())
    try {
      const r = await api.conversationSay(convId, blob)
      setLines((prev) => [
        ...prev,
        { who: 'you', text: r.you_said },
        { who: 'partner', text: r.reply, audio: r.audio },
      ])
      speak(r.audio)
      setPhase('ready')
    } catch (e: unknown) {
      // 422 = no se oyó nada. Merece su propio mensaje: "algo falló" no dice
      // qué hacer, "no se oyó nada" sí.
      const raw = e instanceof Error ? e.message : String(e)
      setErrorKind(/oyó|silen|422/i.test(raw) ? 'silent' : 'turn')
      setError(raw)
      setPhase('ready')
    } finally {
      setWaitSince(null)
    }
  }

  async function end() {
    if (convId == null) return
    setError(null)
    setPhase('closing')
    setWaitSince(Date.now())
    audioRef.current?.pause()
    try {
      setSummary(await api.conversationFinish(convId))
      setPhase('done')
    } catch (e: unknown) {
      // Cerrar es lo último que se hace: si falla, la charla sigue viva y se
      // puede reintentar. Antes se pasaba a 'done' sin resumen y la pantalla
      // se quedaba sin nada que pulsar.
      setErrorKind('close')
      setError(e instanceof Error ? e.message : String(e))
      setPhase('ready')
    } finally {
      setWaitSince(null)
    }
  }

  /* El mismo error, la salida que le corresponde. */
  function retry() {
    if (errorKind === 'open') return void begin()
    if (errorKind === 'close') return void end()
    if (errorKind === 'turn' && lastBlobRef.current) return void send(lastBlobRef.current)
    return void startRecording()
  }

  const errorLine =
    error === null ? null : (
      <ErrorLine onRetry={retry} retryLabel={RETRY_LABEL[errorKind]} className="mb-4">
        {describeError(error, ERROR_FALLBACK[errorKind])}
      </ErrorLine>
    )

  const mine = lines.filter((l) => l.who === 'you').length

  if (phase === 'idle') {
    return (
      <Section className="text-center">
        <p className="font-book text-ink-soft mx-auto max-w-[52ch] text-[16px]">
          Una conversación en inglés, hablada. Nadie te corrige mientras hablas:
          si dices algo mal, la respuesta lo trae bien dicho y sigues. Las
          correcciones — tres como mucho — llegan al final.
        </p>
        {errorLine}
        <Button onClick={begin} onPointerEnter={warm} onFocus={warm} className="mt-8">
          Empezar a hablar
        </Button>
      </Section>
    )
  }

  if (phase === 'done' && summary) {
    return <Summary summary={summary} onAgain={() => {
      setSummary(null); setLines([]); setConvId(null); setPhase('idle')
    }} />
  }

  return (
    <div className="mt-8">
      <div className="border-rule max-h-[52vh] space-y-5 overflow-y-auto border-t pt-6">
        <AnimatePresence initial={false}>
          {lines.map((l, i) => (
            <motion.div
              key={i}
              initial={{ y: 8, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={SLIDE}
              className={l.who === 'you' ? 'text-right' : ''}
            >
              <p className="text-ghost text-[10px] font-semibold tracking-[0.2em] uppercase">
                {l.who === 'you' ? 'Tú' : 'Sam'}
              </p>
              <p
                className={`font-book mt-1 text-[17px] leading-snug ${
                  l.who === 'you' ? 'text-ink-soft' : ''
                }`}
              >
                {l.text}
              </p>
            </motion.div>
          ))}
        </AnimatePresence>
        <div ref={endRef} />
      </div>

      <div className="border-rule mt-6 border-t pt-6 text-center">
        {errorLine}

        {phase === 'opening' && (
          <Waiting since={waitSince}>Sam está pensando cómo empezar</Waiting>
        )}
        {phase === 'thinking' && (
          <Waiting since={waitSince}>Escuchando y respondiendo</Waiting>
        )}
        {phase === 'closing' && (
          <Waiting since={waitSince}>Repasando lo que dijiste</Waiting>
        )}

        {phase === 'ready' && <Button onClick={startRecording}>Hablar</Button>}

        {phase === 'recording' && (
          <Button variant="danger" onClick={stopRecording} className="tnum">
            ● Grabando {String(Math.floor(seconds / 60)).padStart(2, '0')}:
            {String(seconds % 60).padStart(2, '0')} — parar
          </Button>
        )}

        {(phase === 'ready' || phase === 'recording') && mine > 0 && (
          <p className="mt-5">
            <Button variant="text" size="sm" onClick={end} disabled={phase === 'recording'}>
              Terminar y ver correcciones
            </Button>
          </p>
        )}
      </div>
    </div>
  )
}

function Summary({
  summary,
  onAgain,
}: {
  summary: ConversationSummary
  onAgain: () => void
}) {
  const mins = Math.round(((summary.spoken_seconds ?? 0) / 60) * 10) / 10
  return (
    <motion.div
      initial={{ y: 12, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={SLIDE}
    >
      <Section>
        <p className="text-[10px] font-semibold tracking-[0.2em] uppercase">
          Conversación terminada
        </p>
        <p className="font-book text-ink-soft tnum mt-2 text-[15px]">
          {summary.turns ?? 0} turnos · {mins} min hablando
        </p>

        {summary.corrections.length > 0 ? (
          <div className="mt-7 space-y-5">
            {summary.corrections.map((c, i) => (
              <div key={i} className="border-rule border-t pt-4">
                <p className="text-cobalt-deep text-[10px] font-semibold tracking-[0.2em] uppercase">
                  {c.category}
                </p>
                <p className="font-book text-correction mt-2 text-[16px] line-through decoration-1">
                  {c.original}
                </p>
                <p className="font-book mt-1 text-[17px] font-semibold">{c.correction}</p>
                <p className="font-book text-ink-soft mt-1 text-[14px] italic">
                  {c.explanation}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <p className="font-book text-ink-soft mt-6 text-[15px] italic">
            Nada que corregir esta vez.
          </p>
        )}

        {summary.strength && (
          <p className="font-book border-rule mt-7 border-t pt-4 text-[15px]">
            <span className="text-[10px] font-semibold tracking-[0.2em] uppercase">
              Lo que hiciste bien
            </span>
            <br />
            <span className="mt-1 inline-block">{summary.strength}</span>
          </p>
        )}

        <Button onClick={onAgain} className="mt-8">
          Otra conversación
        </Button>
      </Section>
    </motion.div>
  )
}
