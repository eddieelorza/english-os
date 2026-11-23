import { useEffect, useRef, useState } from 'react'
import { api, type NarrationMark, type Narration, type OwnVoiceStatus } from './api'
import { SpeakerIcon, mediaUrl } from './Audio'
import { Button, ErrorLine, Waiting, describeError } from './ui'

const SPEEDS = [0.8, 1] as const

/* Shadowing rig: the coach reads, the current sentence lights up, and you can
   drop the voice and read yourself at any moment ("Now I read"). Repeat
   replays the sentence you are on — the shadowing loop. */
export default function ReadingPlayer(props: {
  textId: number
  onSentence: (index: number | null) => void
}) {
  return <ReadingAudio key={props.textId} {...props} />
}

function ReadingAudio({
  textId,
  onSentence,
}: {
  textId: number
  onSentence: (index: number | null) => void
}) {
  const [marks, setMarks] = useState<NarrationMark[] | null>(null)
  const [src, setSrc] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  /* Reading a whole text aloud is a minute of synthesis on this laptop; the
     button alone cannot say how long it has been at it. */
  const [since, setSince] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<number>(1)
  const [current, setCurrent] = useState<number | null>(null)
  const [voice, setVoice] = useState<'coach' | 'own'>('coach')
  const [own, setOwn] = useState<OwnVoiceStatus | null>(null)
  const recordings = useRef<Partial<Record<'coach' | 'own', Narration>>>({})
  const requestVersion = useRef(0)
  const speedRef = useRef(1)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  useEffect(() => onSentence(current), [current, onSentence])

  useEffect(() => {
    let active = true
    void api.ownVoice(textId).then((status) => {
      if (active) setOwn(status)
    }).catch((e) => {
      if (active) setError(describeError(e instanceof Error ? e.message : null,
        'Voice availability could not be checked.'))
    })
    return () => {
      active = false
      requestVersion.current += 1
      const el = audioRef.current
      if (el) {
        el.ontimeupdate = null
        el.onended = null
        el.onloadedmetadata = null
        el.pause()
      }
      audioRef.current = null
    }
  }, [textId])

  useEffect(() => () => onSentence(null), [onSentence])

  async function prepare(target = voice, autoplay = true) {
    const version = ++requestVersion.current
    setLoading(true)
    setError(null)
    try {
      const r = recordings.current[target] ?? await (
        target === 'own' ? api.narrateOwn(textId) : api.narrate(textId)
      )
      if (version !== requestVersion.current) return
      recordings.current[target] = r
      if (target === 'own') setOwn((status) => status && { ...status, cached: true })
      setMarks(r.marks)
      setSrc(r.path)
      const el = new window.Audio(mediaUrl(r.path))
      el.playbackRate = speedRef.current
      const position = current == null ? 0 : (r.marks[current]?.start ?? 0)
      el.onloadedmetadata = () => { el.currentTime = position }
      el.ontimeupdate = () => {
        if (el.paused) return
        const t = el.currentTime
        const i = r.marks.findIndex((m) => t >= m.start && t < m.end)
        setCurrent(i >= 0 ? i : null)
      }
      el.onended = () => {
        setPlaying(false)
        setCurrent(null)
      }
      audioRef.current = el
      if (autoplay) {
        await el.play()
        if (version === requestVersion.current) setPlaying(true)
      }
    } catch (e) {
      if (version === requestVersion.current) setError(
        describeError(
          e instanceof Error ? e.message : null,
          'The voice engine is unavailable. You can still read on your own.',
        ),
      )
    } finally {
      if (version === requestVersion.current) setLoading(false)
    }
  }

  function changeVoice(next: 'coach' | 'own') {
    if (next === voice || loading) return
    const el = audioRef.current
    if (el) {
      el.ontimeupdate = null
      el.onended = null
      el.onloadedmetadata = null
      el.pause()
    }
    audioRef.current = null
    setPlaying(false)
    setVoice(next)
    setSrc(null)
    setMarks(null)
    setError(null)
    // An uncached paid voice is generated only by the labelled play button.
    if (recordings.current[next] || (next === 'own' && own?.cached)) {
      void prepare(next, false)
    }
  }

  function toggle() {
    const el = audioRef.current
    if (!el) {
      return void prepare()
    }
    if (playing) {
      el.pause()
      setPlaying(false)
    } else {
      void el.play()
      setPlaying(true)
    }
  }

  function stopAndRead() {
    audioRef.current?.pause()
    setPlaying(false)
    setCurrent(null)
  }

  function repeatSentence() {
    const el = audioRef.current
    if (!el || !marks) return
    const i = current ?? 0
    el.currentTime = marks[i].start
    void el.play()
    setPlaying(true)
  }

  function changeSpeed(s: number) {
    setSpeed(s)
    speedRef.current = s
    if (audioRef.current) audioRef.current.playbackRate = s
  }

  return (
    <>
      <div className="border-rule mt-6 flex flex-wrap items-center gap-x-5 gap-y-3 border-y py-3">
        <Button
          variant="primary"
          size="sm"
          onClick={(event) => {
            setSince(performance.timeOrigin + event.timeStamp)
            toggle()
          }}
          disabled={loading}
          className="inline-flex items-center gap-2"
        >
          <SpeakerIcon size={13} playing={playing} />
          {loading ? 'Preparing the voice…' : playing ? 'Pause' : src ? 'Play'
            : voice === 'own' && !own?.cached ? `My voice · ~${own?.chars ?? 0} credits`
            : 'Listen & shadow'}
        </Button>

        {src && (
          <>
            <Button variant="text" tone="cobalt" size="sm" onClick={repeatSentence}>
              Repeat sentence
            </Button>

            {playing && (
              <Button variant="text" size="sm" onClick={stopAndRead}>
                Now I read
              </Button>
            )}
          </>
        )}
        <div className="flex items-baseline gap-2">
          <span className="text-ghost text-xs font-semibold tracking-label uppercase">
            Speed
          </span>
          {SPEEDS.map((s) => (
            <button
              key={s}
              onClick={() => changeSpeed(s)}
              className={`tnum text-xs font-semibold transition-colors ${
                speed === s
                  ? 'text-cobalt-deep underline decoration-2 underline-offset-4'
                  : 'text-ghost hover:text-ink-soft'
              }`}
            >
              {s}×
            </button>
          ))}
        </div>
        {own?.configured && (
          <div className="flex items-baseline gap-2" role="radiogroup" aria-label="Voice">
            {(['coach', 'own'] as const).map((v) => (
              <button
                key={v}
                role="radio"
                aria-checked={voice === v}
                disabled={loading}
                onClick={(event) => {
                  setSince(performance.timeOrigin + event.timeStamp)
                  changeVoice(v)
                }}
                className={`text-xs font-semibold transition-colors ${
                  voice === v
                    ? 'text-cobalt-deep underline decoration-2 underline-offset-4'
                    : 'text-ghost hover:text-ink-soft'
                }`}
              >
                {v === 'coach' ? 'Coach' : 'My voice'}
              </button>
            ))}
          </div>
        )}
      </div>

      {loading && (
        <Waiting since={since}>
          {voice === 'own' ? 'Preparing your voice…' : 'The coach is reading it through before it speaks…'}
        </Waiting>
      )}

      {error && (
        <ErrorLine onRetry={() => {
          setSince(Date.now())
          void prepare()
        }}>
          {error}
        </ErrorLine>
      )}
    </>
  )
}
