import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { api } from './api'
import { mediaUrl } from './Audio'
import type { ConversationSummary } from './api'
import { Button, ErrorLine, SLIDE, Section, Waiting } from './ui'

type Line = { who: 'you' | 'partner'; text: string; audio?: string | null }
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
  const [seconds, setSeconds] = useState(0)

  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<number | undefined>(undefined)
  const endRef = useRef<HTMLDivElement | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  useEffect(() => () => window.clearInterval(timerRef.current), [])

  /* Precalentar al abrir: cargar Ollama (4.3 s) y Kokoro (5.6 s) cuesta ~10 s
     y ocurriría justo al pulsar el botón. Aquí ocurre mientras se lee la
     introducción. Si falla, el primer turno sólo tarda más. */
  useEffect(() => {
    void api.conversationWarm().catch(() => undefined)
  }, [])
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
    try {
      const r = await api.conversationStart()
      setConvId(r.conversation_id)
      setLines([{ who: 'partner', text: r.reply, audio: r.audio }])
      speak(r.audio)
      setPhase('ready')
    } catch {
      setError('No pude abrir la conversación — revisa el modelo en Reading.')
      setPhase('idle')
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
        void send(new Blob(chunksRef.current, { type: 'audio/webm' }))
      }
      recorderRef.current = rec
      rec.start()
      setSeconds(0)
      timerRef.current = window.setInterval(() => setSeconds((s) => s + 1), 1000)
      setPhase('recording')
    } catch {
      setError('No pude usar el micrófono. Dale permiso al navegador.')
    }
  }

  function stopRecording() {
    window.clearInterval(timerRef.current)
    recorderRef.current?.stop()
    setPhase('thinking')
  }

  async function send(blob: Blob) {
    if (convId == null) return
    try {
      const r = await api.conversationSay(convId, blob)
      setLines((prev) => [
        ...prev,
        { who: 'you', text: r.you_said },
        { who: 'partner', text: r.reply, audio: r.audio },
      ])
      speak(r.audio)
      setPhase('ready')
    } catch (e) {
      // 422 = no se oyó nada. Merece su propio mensaje: "algo falló" no dice
      // qué hacer, "no se oyó nada" sí.
      const silent = e instanceof Error && /oyó|silen/i.test(e.message)
      setError(silent ? 'No se oyó nada. ¿El micrófono estaba mudo?'
                      : 'Se cayó el turno. Prueba otra vez.')
      setPhase('ready')
    }
  }

  async function end() {
    if (convId == null) return
    setPhase('closing')
    audioRef.current?.pause()
    try {
      setSummary(await api.conversationFinish(convId))
    } catch {
      setError('No pude cerrar la conversación.')
    }
    setPhase('done')
  }

  const mine = lines.filter((l) => l.who === 'you').length

  if (phase === 'idle') {
    return (
      <Section className="text-center">
        <p className="font-book text-ink-soft mx-auto max-w-[52ch] text-[16px]">
          Una conversación en inglés, hablada. Nadie te corrige mientras hablas:
          si dices algo mal, la respuesta lo trae bien dicho y sigues. Las
          correcciones — tres como mucho — llegan al final.
        </p>
        {error && <ErrorLine>{error}</ErrorLine>}
        <Button onClick={begin} className="mt-8">
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
        {error && <ErrorLine className="mb-4">{error}</ErrorLine>}

        {phase === 'opening' && <Waiting>Sam está pensando cómo empezar</Waiting>}
        {phase === 'thinking' && <Waiting>Escuchando y respondiendo</Waiting>}
        {phase === 'closing' && <Waiting>Repasando lo que dijiste</Waiting>}

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
