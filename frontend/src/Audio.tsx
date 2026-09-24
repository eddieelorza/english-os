import { useEffect, useRef, useState } from 'react'

export const mediaUrl = (path: string) => `/api/media/${path}`

/* The speaker mark: a drawn glyph in the workbook's ink, never an emoji.
   Two sizes — inline beside a word, or standalone on the flashcard. */
export function SpeakerIcon({ size = 14, playing = false }: { size?: number; playing?: boolean }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M3 6h2.5L9 3v10L5.5 10H3z" fill="currentColor" stroke="none" />
      <path d="M11.5 5.5a3.5 3.5 0 0 1 0 5" opacity={playing ? 1 : 0.75} />
      {playing && <path d="M13.5 3.5a6.5 6.5 0 0 1 0 9" opacity={0.5} />}
    </svg>
  )
}

/* Plays a media file from the deck (or a generated one). Silent no-op when
   the word has no recording, so callers never branch. */
export function PlayButton({
  src,
  label,
  size = 14,
  className = '',
  autoPlay = false,
}: {
  src: string | null
  label: string
  size?: number
  className?: string
  /* Suena solo al aparecer. La preferencia se lee de una ref para que
     encenderla o apagarla a mitad de una card no vuelva a disparar el audio:
     sólo un `src` nuevo lo hace. */
  autoPlay?: boolean
}) {
  const [playing, setPlaying] = useState(false)
  const ref = useRef<HTMLAudioElement | null>(null)
  const auto = useRef(autoPlay)
  auto.current = autoPlay

  /* El audio se construye aquí y no en el click, para poder arrancarlo solo
     — y se descarta al cambiar de palabra: antes el objeto sobrevivía al
     cambio de `src` y el botón habría reproducido la palabra anterior. */
  useEffect(() => {
    setPlaying(false)
    if (!src) {
      ref.current = null
      return
    }
    const audio = new window.Audio(mediaUrl(src))
    audio.onended = () => setPlaying(false)
    ref.current = audio
    if (auto.current) {
      setPlaying(true)
      // El navegador puede negarse hasta que haya habido un gesto del
      // usuario. No es un error que merezca romper nada: el botón sigue ahí.
      void audio.play().catch(() => setPlaying(false))
    }
    return () => {
      audio.pause()
      audio.onended = null
    }
  }, [src])

  if (!src) return null

  function toggle(e: React.MouseEvent) {
    e.stopPropagation()
    if (!ref.current) return
    if (playing) {
      ref.current.pause()
      ref.current.currentTime = 0
      setPlaying(false)
    } else {
      void ref.current.play()
      setPlaying(true)
    }
  }

  return (
    <button
      onClick={toggle}
      aria-label={label}
      title={label}
      className={`text-cobalt-deep hover:text-cobalt inline-flex shrink-0 items-center transition-colors ${
        playing ? 'text-cobalt' : ''
      } ${className}`}
    >
      <SpeakerIcon size={size} playing={playing} />
    </button>
  )
}
