import { useEffect, useRef, useState } from 'react'
import { api, type NarrationMark } from './api'
import { SpeakerIcon, mediaUrl } from './Audio'
import { Button, ErrorLine, Waiting, describeError } from './ui'

const SPEEDS = [0.8, 1] as const

/* Shadowing rig: the coach reads, the current sentence lights up, and you can
   drop the voice and read yourself at any moment ("Now I read"). Repeat
   replays the sentence you are on — the shadowing loop. */
export default function ReadingPlayer({
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
  const audioRef = useRef<HTMLAudioElement | null>(null)

  useEffect(() => onSentence(current), [current, onSentence])

  useEffect(() => {
    return () => {
      audioRef.current?.pause()
      onSentence(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function prepare() {
    setLoading(true)
    setSince(Date.now())
    setError(null)
    try {
      const r = await api.narrate(textId)
      setMarks(r.marks)
      setSrc(r.path)
      const el = new window.Audio(mediaUrl(r.path))
      el.playbackRate = speed
      el.ontimeupdate = () => {
        const t = el.currentTime
        const i = r.marks.findIndex((m) => t >= m.start && t < m.end)
        setCurrent(i >= 0 ? i : null)
      }
      el.onended = () => {
        setPlaying(false)
        setCurrent(null)
      }
      audioRef.current = el
      void el.play()
      setPlaying(true)
    } catch (e) {
      setError(
        describeError(
          e instanceof Error ? e.message : null,
          'The voice engine is unavailable. You can still read on your own.',
        ),
      )
    } finally {
      setLoading(false)
    }
  }

  function toggle() {
    const el = audioRef.current
    if (!el) return void prepare()
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
    if (audioRef.current) audioRef.current.playbackRate = s
  }

  return (
    <>
      <div className="border-rule mt-6 flex flex-wrap items-center gap-x-5 gap-y-3 border-y py-3">
        <Button
          variant="primary"
          size="sm"
          onClick={toggle}
          disabled={loading}
          className="inline-flex items-center gap-2"
        >
          <SpeakerIcon size={13} playing={playing} />
          {loading ? 'Preparing the voice…' : playing ? 'Pause' : src ? 'Play' : 'Listen & shadow'}
        </Button>

        {src && (
          <>
            <Button variant="text" tone="cobalt" size="sm" onClick={repeatSentence}>
              Repeat sentence
            </Button>

            <div className="flex items-baseline gap-2">
              <span className="text-ghost text-[10px] font-semibold tracking-[0.18em] uppercase">
                Speed
              </span>
              {SPEEDS.map((s) => (
                <button
                  key={s}
                  onClick={() => changeSpeed(s)}
                  className={`tnum text-[12px] font-semibold transition-colors ${
                    speed === s
                      ? 'text-cobalt-deep underline decoration-2 underline-offset-4'
                      : 'text-ghost hover:text-ink-soft'
                  }`}
                >
                  {s}×
                </button>
              ))}
            </div>

            {playing && (
              <Button variant="text" size="sm" onClick={stopAndRead}>
                Now I read
              </Button>
            )}
          </>
        )}
      </div>

      {loading && (
        <Waiting since={since}>The coach is reading it through before it speaks…</Waiting>
      )}

      {error && <ErrorLine onRetry={() => void prepare()}>{error}</ErrorLine>}
    </>
  )
}
