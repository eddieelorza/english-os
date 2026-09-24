import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'motion/react'
import { api } from './api'
import type { ShadowSession, ShadowSummary } from './api'
import { mediaUrl } from './Audio'
import { Button, ErrorLine, Page, PageHeader, SLIDE, Section, Waiting, fmt } from './ui'

const SPEEDS = [1, 0.85, 0.7] as const

/* Shadowing sobre vídeo: escuchas una línea, la repites, pasas a la siguiente.

   Nada de grabar aquí a propósito. El shadowing es repetir encima o justo
   detrás de lo que oyes; meter grabar-escucharte-comparar en cada línea
   convierte tres segundos de práctica en treinta de gestión. Para grabarte y
   que te corrijan ya está Speaking. */
export default function ShadowingPage() {
  const [sessions, setSessions] = useState<ShadowSummary[]>([])
  const [session, setSession] = useState<ShadowSession | null>(null)
  const [url, setUrl] = useState('')
  const [working, setWorking] = useState(false)
  const [progress, setProgress] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cursor, setCursor] = useState(0)
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1)
  const [playing, setPlaying] = useState(false)

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const stopAtRef = useRef<number>(0)

  useEffect(() => {
    api.shadowList().then((r) => setSessions(r.sessions)).catch(() => undefined)
  }, [])

  /* Un solo <audio> para todo el vídeo: se salta al inicio de la línea y se
     para en su final. Cargar un archivo por línea multiplicaría las peticiones
     y metería un parpadeo entre repeticiones. */
  useEffect(() => {
    if (!session?.audio_path) return
    const a = new Audio(mediaUrl(session.audio_path))
    a.preload = 'auto'
    const onTime = () => {
      if (a.currentTime >= stopAtRef.current) {
        a.pause()
        setPlaying(false)
      }
    }
    a.addEventListener('timeupdate', onTime)
    audioRef.current = a
    return () => {
      a.pause()
      a.removeEventListener('timeupdate', onTime)
      audioRef.current = null
    }
  }, [session?.audio_path])

  const line = session?.lines[cursor]

  const play = useCallback(() => {
    const a = audioRef.current
    if (!a || !line) return
    a.playbackRate = speed
    a.currentTime = line.start_s
    stopAtRef.current = line.end_s
    setPlaying(true)
    void a.play().catch(() => setPlaying(false))
  }, [line, speed])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!session || (e.target as HTMLElement)?.tagName === 'INPUT') return
      if (e.code === 'Space') {
        e.preventDefault()
        play()
      }
      if (e.code === 'Enter') {
        e.preventDefault()
        void advance()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  async function load(id: number) {
    setError(null)
    try {
      const s = await api.shadowGet(id)
      setSession(s)
      setCursor(s.lines.findIndex((l) => !l.done_at) === -1
        ? 0
        : s.lines.findIndex((l) => !l.done_at))
    } catch {
      setError('No pude abrir esa sesión.')
    }
  }

  async function submit() {
    if (!url.trim() || working) return
    setWorking(true)
    setError(null)
    setProgress(null)
    try {
      const created = await api.shadowCreate(url.trim())
      if (created.ready && created.session) {
        setSession(created.session)
        setCursor(0)
        setUrl('')
      } else if (created.job_id) {
        // El trabajo puede tardar varios minutos: transcribir va a ~0.25x del
        // audio y encima espera turno en la cola. Se sondea en vez de dejar
        // una petición HTTP colgada, que se cae sola.
        setProgress(created.title || 'ese vídeo')
        let job = await api.job(created.job_id)
        while (job.status === 'queued' || job.status === 'running') {
          await new Promise((r) => setTimeout(r, 2000))
          job = await api.job(created.job_id)
        }
        if (job.status !== 'done') {
          throw new Error(job.error || 'La transcripción falló.')
        }
        const sid = (job.result as { session_id?: number } | null)?.session_id
        if (sid) {
          setSession(await api.shadowGet(sid))
          setCursor(0)
          setUrl('')
        }
      }
      api.shadowList().then((r) => setSessions(r.sessions)).catch(() => undefined)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No pude preparar ese vídeo.')
    }
    setProgress(null)
    setWorking(false)
  }

  async function advance() {
    if (!session || !line) return
    try {
      const s = await api.shadowMark(line.id, true)
      setSession(s)
    } catch {
      /* marcar es cosmético: si falla, no se corta la práctica */
    }
    setCursor((c) => Math.min(c + 1, (session.lines.length || 1) - 1))
  }

  if (!session) {
    return (
      <Page width="study">
        <PageHeader
          title="Shadowing"
          subtitle={
            <p className="max-w-[58ch] text-[16px]">
              Pega un vídeo de YouTube. Se baja el audio, se transcribe y te queda
              línea por línea para repetir detrás. Funciona mejor con gente
              hablando —una charla, una entrevista— que con canciones: al cantar se
              estiran las vocales y el acento lo manda la melodía, no el idioma.
            </p>
          }
        />

        <Section>
          <div className="flex gap-3">
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
              placeholder="https://www.youtube.com/watch?v=…"
              disabled={working}
              className="border-rule font-book focus:border-cobalt-deep flex-1 border-b bg-transparent pb-2 text-[15px] outline-none disabled:opacity-50"
            />
            <Button onClick={submit} disabled={working || !url.trim()} size="sm">
              {working ? 'Preparando…' : 'Preparar'}
            </Button>
          </div>
          {working && (
            <Waiting>
              {progress
                ? `Preparando «${progress}». Transcribir tarda algo más que la
                   propia duración del vídeo, y antes espera turno si hay otra
                   cosa generándose. Puedes irte a otra pantalla: sigue en
                   marcha.`
                : 'Leyendo el vídeo…'}
            </Waiting>
          )}
          {error && <ErrorLine>{error}</ErrorLine>}
        </Section>

        {sessions.length > 0 && (
          <Section label="Ya preparados">
            <ul className="mt-4 space-y-3">
              {sessions.map((s) => (
                <li key={s.id}>
                  <button
                    onClick={() => load(s.id)}
                    className="group w-full text-left"
                  >
                    <span className="font-book group-hover:text-cobalt-deep text-[16px] transition-colors">
                      {s.title || 'Sin título'}
                    </span>
                    <span className="tnum text-ghost ml-2 text-[12px]">
                      {s.channel ? `${s.channel} · ` : ''}
                      {fmt(s.done)}/{fmt(s.lines)} líneas
                      {s.confidence !== null && s.confidence <= -0.8
                        ? ' · transcripción dudosa'
                        : ''}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Section>
        )}
      </Page>
    )
  }

  const total = session.lines.length
  return (
    <Page width="study">
      <Button variant="text" size="sm" onClick={() => setSession(null)}>
        ← Otro vídeo
      </Button>
      <h2 className="mt-3 text-3xl font-extrabold tracking-tight">
        {session.title || 'Shadowing'}
      </h2>
      <p className="tnum text-ghost mt-1 text-[12px]">
        {session.channel} · {fmt(session.done)}/{fmt(total)} líneas
      </p>

      {session.confidence !== null && session.confidence <= -0.8 && (
        <ErrorLine className="max-w-[54ch]">
          La transcripción de este vídeo salió poco fiable. Fíate de lo que oyes
          antes que de lo que lees.
        </ErrorLine>
      )}

      <motion.div
        key={cursor}
        initial={{ y: 10, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={SLIDE}
        className="border-rule-strong mt-8 border bg-white/70 px-6 py-10 text-center sm:px-10"
      >
        <p className="tnum text-ghost text-[10px] font-semibold tracking-[0.2em] uppercase">
          Línea {cursor + 1} de {total}
        </p>
        <p className="font-book mt-4 text-2xl leading-snug">{line?.text}</p>

        <div className="mt-8 flex items-center justify-center gap-3">
          <Button onClick={play}>{playing ? '♪ sonando' : 'Escuchar'}</Button>
          {SPEEDS.map((s) => (
            <button
              key={s}
              onClick={() => setSpeed(s)}
              className={`tnum px-3 py-3 text-[11px] font-semibold transition-colors ${
                speed === s ? 'text-cobalt-deep' : 'text-ghost hover:text-ink-soft'
              }`}
            >
              {s === 1 ? '1×' : `${s}×`}
            </button>
          ))}
        </div>
      </motion.div>

      <div className="mt-6 flex items-center justify-between">
        <Button
          variant="text"
          size="sm"
          onClick={() => setCursor((c) => Math.max(0, c - 1))}
          disabled={cursor === 0}
        >
          ← Anterior
        </Button>
        <Button variant="secondary" size="sm" onClick={advance}>
          Hecha, siguiente →
        </Button>
      </div>

      <p className="tnum text-ghost mt-6 text-center text-[11px]">
        espacio para volver a oírla · enter para pasar a la siguiente
      </p>
    </Page>
  )
}
