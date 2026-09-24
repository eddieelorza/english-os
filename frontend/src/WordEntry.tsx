import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { api } from './api'
import type { Review, Word, WordDetail, WordStatus } from './api'
import { SLIDE, fmt } from './ui'
import { PlayButton } from './Audio'

const STATUS_ORDER: WordStatus[] = ['NEW', 'LEARNING', 'FAMILIAR', 'MASTERED']

/* Status is a hairline mark in the margin gutter — the ink dries as you
   master: dashed ghost → solid cobalt → faded cobalt → none. */
function MarginMark({ status }: { status: WordStatus }) {
  if (status === 'MASTERED') return <span className="w-[3px] shrink-0" aria-hidden />
  const style =
    status === 'NEW'
      ? { borderLeft: '1px dashed var(--color-rule-strong)' }
      : status === 'LEARNING'
        ? { background: 'var(--color-cobalt)', width: 2 }
        : { background: 'color-mix(in srgb, var(--color-cobalt) 35%, transparent)', width: 2 }
  return <span aria-hidden className="w-[3px] shrink-0 self-stretch" style={style} />
}

const KIND_LABEL: Record<string, string> = {
  phrasal_verb: 'phrasal verb',
  expression: 'expression',
  sentence: 'sentence',
}

export default function WordEntry({
  word,
  index,
  open,
  onToggle,
  onPatched,
}: {
  word: Word
  index: number
  open: boolean
  onToggle: () => void
  onPatched: (w: Word) => void
}) {
  const [detail, setDetail] = useState<WordDetail | null>(null)
  const [esOpen, setEsOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const ghost = word.status === 'NEW'

  function toggle() {
    onToggle()
    if (!open && !detail) {
      api.word(word.id).then(setDetail).catch(() => undefined)
    }
    if (open) setEsOpen(false)
  }

  async function setStatus(s: WordStatus) {
    if (s === word.status || saving) return
    setSaving(true)
    try {
      const updated = await api.patchWord(word.id, { status: s })
      onPatched(updated)
      setDetail(updated)
    } finally {
      setSaving(false)
    }
  }

  return (
    <article role="listitem" className="border-rule flex border-b">
      <MarginMark status={word.status} />
      <div className="min-w-0 flex-1">
        {/* Entry line */}
        <button
          onClick={toggle}
          aria-expanded={open}
          className={`hover:bg-cobalt-wash/60 flex w-full items-baseline gap-4 py-3.5 pr-4 pl-4 text-left transition-colors ${
            ghost && !open ? 'opacity-55' : ''
          }`}
        >
          <span className="tnum text-ghost w-10 shrink-0 text-right text-[12px]">{index}</span>
          <span className="font-book min-w-0 text-[17px] leading-snug font-semibold">
            {word.word}
            <PlayButton src={word.audio_word} label={`Hear ${word.word}`} className="ml-2 align-middle" />
            {word.pronunciation && (
              <span className="text-ghost ml-2.5 inline-block text-[13px] font-normal">
                /{word.pronunciation}/
              </span>
            )}
            {KIND_LABEL[word.kind] && (
              <span className="text-cobalt-deep ml-2.5 align-middle text-[10px] font-sans font-semibold tracking-[0.14em] uppercase">
                {KIND_LABEL[word.kind]}
              </span>
            )}
          </span>
          <span className="tnum text-ghost ml-auto shrink-0 text-right text-[12px]">
            {word.status === 'NEW'
              ? 'not studied'
              : `${fmt(word.review_count)} rev · ${word.interval_days ? `${fmt(word.interval_days)} d` : '—'}`}
          </span>
        </button>

        {/* Open entry */}
        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={SLIDE}
              className="overflow-hidden"
            >
              <div className="pr-5 pb-6 pl-[58px] lg:pl-[72px]">
                {word.meaning_en && (
                  <p className="font-book max-w-[68ch] text-[15px] leading-relaxed">{word.meaning_en}</p>
                )}
                {word.example_en && (
                  <p className="font-book text-ink-soft mt-2 flex max-w-[68ch] items-start gap-2 text-[15px] leading-relaxed italic">
                    <span>“{word.example_en}”</span>
                    <PlayButton
                      src={word.audio_example}
                      label="Hear the example"
                      size={13}
                      className="mt-1"
                    />
                  </p>
                )}

                {/* The covered Spanish column — the Assimil ritual */}
                {(word.meaning_es || word.example_es) && (
                  <div className="mt-4 flex items-center overflow-hidden">
                    <AnimatePresence initial={false} mode="wait">
                      {esOpen ? (
                        <motion.p
                          key="es"
                          initial={{ x: -24, opacity: 0 }}
                          animate={{ x: 0, opacity: 1 }}
                          exit={{ x: -24, opacity: 0 }}
                          transition={SLIDE}
                          className="font-book text-cobalt-deep max-w-[68ch] text-[15px]"
                          lang="es"
                        >
                          {word.meaning_es}
                          {word.example_es && (
                            <span className="text-ink-soft italic"> — {word.example_es}</span>
                          )}
                        </motion.p>
                      ) : (
                        <motion.button
                          key="cover"
                          onClick={() => setEsOpen(true)}
                          initial={{ x: -12, opacity: 0 }}
                          animate={{ x: 0, opacity: 1 }}
                          exit={{ x: 24, opacity: 0 }}
                          transition={SLIDE}
                          className="border-cobalt/40 text-cobalt-deep hover:bg-cobalt-wash rounded-sm border border-dashed px-3 py-1 text-[11px] font-semibold tracking-[0.18em] uppercase transition-colors"
                        >
                          Uncover Spanish
                        </motion.button>
                      )}
                    </AnimatePresence>
                  </div>
                )}

                {/* Instrument readouts */}
                {word.status !== 'NEW' && (
                  <dl className="tnum text-ink-soft mt-5 flex flex-wrap gap-x-8 gap-y-1 text-[12px]">
                    <Readout k="Reviews" v={fmt(word.review_count)} />
                    <Readout
              k="Interval"
              v={word.interval_days ? `${fmt(word.interval_days)} ${word.interval_days === 1 ? 'day' : 'days'}` : '—'}
            />
                    <Readout k="Ease" v={word.ease ? word.ease.toFixed(2) : '—'} />
                    <Readout k="Lapses" v={fmt(word.lapses)} />
                    <Readout k="Used in writing" v={fmt(word.times_used)} />
                    {word.last_reviewed_on && (
                      <Readout k="Last review" v={word.last_reviewed_on.slice(0, 10)} />
                    )}
                  </dl>
                )}

                {/* Review history */}
                {detail && detail.reviews.length > 0 && (
                  <div className="mt-4">
                    <h4 className="text-ghost text-[10px] font-semibold tracking-[0.18em] uppercase">
                      Recent reviews
                    </h4>
                    <ul className="tnum text-ink-soft mt-1.5 space-y-0.5 text-[12px]">
                      {detail.reviews.slice(0, 5).map((r, i) => (
                        <li key={i} className="flex gap-4">
                          <span className="w-24">{r.reviewed_at.slice(0, 10)}</span>
                          <span className={r.rating === 1 ? 'text-correction' : ''}>
                            {ratingLabel(r)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Status control — a ruled workbook line, not chips */}
                <div className="border-rule mt-6 flex items-center gap-5 border-t pt-3">
                  <span className="text-ghost text-[10px] font-semibold tracking-[0.18em] uppercase">
                    Status
                  </span>
                  <div className="flex gap-4" role="radiogroup" aria-label="Word status">
                    {STATUS_ORDER.map((s) => {
                      const active = word.status === s
                      return (
                        <button
                          key={s}
                          role="radio"
                          aria-checked={active}
                          disabled={saving}
                          onClick={() => setStatus(s)}
                          className={`text-[11px] font-semibold tracking-[0.14em] uppercase transition-colors disabled:opacity-40 ${
                            active
                              ? 'text-cobalt-deep underline decoration-2 underline-offset-4'
                              : 'text-ghost hover:text-ink-soft'
                          }`}
                        >
                          {s.toLowerCase()}
                        </button>
                      )
                    })}
                  </div>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </article>
  )
}

function Readout({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex gap-1.5">
      <dt className="text-ghost">{k}</dt>
      <dd className="text-ink font-semibold">{v}</dd>
    </div>
  )
}

function ratingLabel(r: Review): string {
  const names: Record<number, string> = { 1: 'again', 2: 'hard', 3: 'good', 4: 'easy' }
  return `${names[r.rating] ?? r.rating}${r.interval_days ? ` → ${Math.round(r.interval_days)} d` : ''}`
}
