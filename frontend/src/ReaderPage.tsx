import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AnimatePresence, motion } from 'motion/react'
import { api, STOPWORDS } from './api'
import { PlayButton } from './Audio'
import ReadingPlayer from './ReadingPlayer'
import ComprehensionQuiz from './ComprehensionQuiz'
import type { LexiconEntry, SentenceExplanation, TextDetail, WordStatus } from './api'
import { Page, PageHeader, Button, ButtonLink, RuledSkeleton, ErrorLine, Waiting, SLIDE, fmt } from './ui'

const TOKEN_SPLIT = /([A-Za-z]+(?:['’][A-Za-z]+)?)/
/* Must mirror tts.split_sentences on the server, or the karaoke marks and the
   rendered sentences drift apart. */
const SENTENCE_SPLIT = /[^.!?]+[.!?]*\s*/g

/* Reader ink (DESIGN.md): status marks as underlines that dry with mastery.
   Unknown words wear the cobalt dashed invitation; stopwords stay plain. */
const UNDERLINE: Record<string, string> = {
  unknown: 'underline decoration-cobalt/60 decoration-dashed decoration-1 underline-offset-4',
  NEW: 'underline decoration-rule-strong decoration-dashed decoration-1 underline-offset-4',
  LEARNING: 'underline decoration-cobalt decoration-2 underline-offset-4',
  FAMILIAR: 'underline decoration-cobalt/35 decoration-2 underline-offset-4',
  MASTERED: '',
}

interface Popup {
  token: string
  entry: LexiconEntry | null
  top: number
  left: number
}

export default function ReaderPage() {
  const { id } = useParams()
  const [text, setText] = useState<TextDetail | null>(null)
  const [error, setError] = useState(false)
  const [popup, setPopup] = useState<Popup | null>(null)
  const [esOpen, setEsOpen] = useState(false)
  const [added, setAdded] = useState<string[]>([])
  const [finished, setFinished] = useState<{ seconds: number } | null>(null)
  const [spoken, setSpoken] = useState<number | null>(null)
  const [explainIndex, setExplainIndex] = useState<number | null>(null)
  const [explanation, setExplanation] = useState<SentenceExplanation | null>(null)
  const [explaining, setExplaining] = useState(false)

  async function askExplain(index: number, sentence: string) {
    if (explainIndex === index) {
      setExplainIndex(null)
      setExplanation(null)
      return
    }
    setPopup(null)
    setExplainIndex(index)
    setExplanation(null)
    setExplaining(true)
    try {
      setExplanation(await api.explain(sentence, Number(id)))
    } catch {
      setExplanation(null)
    } finally {
      setExplaining(false)
    }
  }
  const startRef = useRef(Date.now())
  const articleRef = useRef<HTMLDivElement>(null)

  /* Lifted out of the effect so the error state has a real way back in. */
  const load = useCallback(() => {
    api
      .text(Number(id))
      .then((t) => {
        setText(t)
        startRef.current = Date.now()
      })
      .catch(() => setError(true))
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  const lookup = useCallback(
    (token: string): LexiconEntry | null => text?.lexicon[token.toLowerCase().replace('’', "'")] ?? null,
    [text],
  )

  function classFor(token: string): string {
    const low = token.toLowerCase().replace('’', "'")
    if (STOPWORDS.has(low)) return ''
    const entry = lookup(token)
    if (!entry) return UNDERLINE.unknown
    return UNDERLINE[entry.status]
  }

  function openPopup(e: React.MouseEvent<HTMLButtonElement>, token: string) {
    const article = articleRef.current
    if (!article) return
    const r = e.currentTarget.getBoundingClientRect()
    const a = article.getBoundingClientRect()
    const width = Math.min(340, a.width)
    setEsOpen(false)
    setPopup({
      token,
      entry: lookup(token),
      top: r.bottom - a.top + 10,
      left: Math.max(0, Math.min(r.left - a.left, a.width - width)),
    })
  }

  function updateLexicon(entry: LexiconEntry) {
    setText((t) => (t ? { ...t, lexicon: { ...t.lexicon, [entry.normalized]: entry } } : t))
    setPopup((p) => (p ? { ...p, entry } : p))
  }

  async function addToVocabulary(token: string) {
    const sentence = sentenceFor(text?.body ?? '', token)
    const w = await api.addWord({ word: token.toLowerCase(), status: 'LEARNING', example_en: sentence })
    const entry: LexiconEntry = {
      id: w.id,
      word: w.word,
      normalized: token.toLowerCase(),
      status: w.status,
      kind: w.kind,
      meaning_en: w.meaning_en,
      meaning_es: w.meaning_es,
      pronunciation: w.pronunciation,
      example_en: w.example_en,
      review_count: w.review_count,
      interval_days: w.interval_days,
    }
    updateLexicon(entry)
    setAdded((a) => (a.includes(w.word) ? a : [...a, w.word]))
  }

  async function setStatus(entry: LexiconEntry, status: WordStatus) {
    const w = await api.patchWord(entry.id, { status })
    updateLexicon({ ...entry, status: w.status })
  }

  async function finish() {
    const seconds = Math.max(1, Math.round((Date.now() - startRef.current) / 1000))
    await api.finishText(Number(id), seconds, added.length)
    setPopup(null)
    setFinished({ seconds })
  }

  const stats = useMemo(() => {
    if (!text) return null
    const tokens = text.body.split(TOKEN_SPLIT).filter((_, i) => i % 2 === 1)
    const unique = new Set(tokens.map((t) => t.toLowerCase().replace('’', "'")))
    let known = 0,
      learning = 0,
      unknown = 0
    unique.forEach((t) => {
      if (STOPWORDS.has(t)) return
      const e = text.lexicon[t]
      if (!e) unknown++
      else if (e.status === 'LEARNING' || e.status === 'NEW') learning++
      else known++
    })
    return { total: tokens.length, unique: unique.size, known, learning, unknown }
  }, [text])

  if (error)
    return (
      <Page width="study" bottom="pb-24">
        <ErrorLine
          onRetry={() => {
            setError(false)
            load()
          }}
        >
          This reading could not be opened.
        </ErrorLine>
        <ButtonLink to="/reading" variant="text" tone="cobalt" size="sm" className="mt-4">
          ← Back to the shelf
        </ButtonLink>
      </Page>
    )
  if (!text)
    return (
      <Page width="study" bottom="pb-24">
        <RuledSkeleton lines={5} />
      </Page>
    )

  /* Finished colophon */
  if (finished && stats)
    return (
      <Page width="study" bottom="pb-24">
        <PageHeader overline="Reading finished" title={text.title} serif />
        <dl className="tnum border-rule mt-8 border-t">
          <Colophon k="Time" v={fmtTime(finished.seconds)} />
          <Colophon k="Length" v={`${fmt(stats.total)} words · ${fmt(stats.unique)} unique`} />
          <Colophon k="Known" v={fmt(stats.known)} />
          <Colophon k="Learning" v={fmt(stats.learning)} />
          <Colophon k="Still unknown" v={fmt(stats.unknown)} />
          <Colophon k="Added to vocabulary" v={added.length ? added.join(', ') : 'none'} />
        </dl>
        <div className="mt-10 flex gap-6">
          <ButtonLink to="/reading" variant="text" tone="cobalt">
            ← Back to the shelf
          </ButtonLink>
          <ButtonLink to="/vocabulary" variant="text">
            Review vocabulary
          </ButtonLink>
        </div>
      </Page>
    )

  return (
    <Page width="study" bottom="pb-24">
      <PageHeader
        overline={
          <Link to="/reading" className="hover:text-ink-soft">
            ← Shelf
          </Link>
        }
        title={text.title}
        serif
        meta={
          stats && (
            <span className="tnum text-ghost text-[12px]">
              {fmt(stats.total)} words · {fmt(stats.unknown)} unknown
            </span>
          )
        }
      />

      {/* Listen & shadow */}
      <ReadingPlayer textId={text.id} onSentence={setSpoken} />

      {/* The page itself */}
      <div ref={articleRef} className="relative">
        <article className="font-book mt-8 max-w-[68ch] text-[17px] leading-[1.75]">
          {(() => {
            let sentenceIndex = -1
            return text.body.split(/\n+/).map((para, pi) => (
              <p key={pi} className="mb-5">
                {(para.match(SENTENCE_SPLIT) ?? [para]).map((sentence) => {
                  if (!sentence.trim()) return null
                  sentenceIndex += 1
                  const idx = sentenceIndex
                  const lit = spoken === idx
                  const explaining = explainIndex === idx
                  return (
                    <span
                      key={idx}
                      className={`group ${
                        lit
                          ? 'bg-cobalt-wash -mx-0.5 rounded-[2px] px-0.5 transition-colors'
                          : explaining
                            ? 'bg-cobalt-wash/60 -mx-0.5 rounded-[2px] px-0.5'
                            : spoken != null
                              ? 'opacity-55 transition-opacity'
                              : 'transition-opacity'
                      }`}
                    >
                      {sentence.split(TOKEN_SPLIT).map((part, i) =>
                        i % 2 === 1 ? (
                          <button
                            key={i}
                            onClick={(e) => openPopup(e, part)}
                            className={`hover:bg-cobalt-wash rounded-[2px] transition-colors ${classFor(part)}`}
                          >
                            {part}
                          </button>
                        ) : (
                          <span key={i}>{part}</span>
                        ),
                      )}
                      {/* The sentence mark. `hidden`, not `opacity-0`: an
                          invisible glyph would still take a slot and open a
                          ragged gap after every sentence. */}
                      <button
                        onClick={() => askExplain(idx, sentence.trim())}
                        aria-label="Explain this sentence"
                        title="Explain this sentence"
                        className={`text-cobalt-deep font-ui align-baseline text-[10px] font-semibold ${
                          explaining ? 'inline' : 'hidden group-hover:inline'
                        }`}
                      >
                        ¶
                      </button>
                    </span>
                  )
                })}
              </p>
            ))
          })()}
        </article>

        {/* Dictionary slip */}
        <AnimatePresence>
          {popup && (
            <motion.aside
              key={`${popup.token}-${popup.top}`}
              initial={{ y: -8, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: -8, opacity: 0 }}
              transition={SLIDE}
              style={{ top: popup.top, left: popup.left, width: 340, maxWidth: '100%' }}
              className="border-rule-strong absolute z-10 border bg-white p-4 shadow-[0_6px_24px_rgba(22,24,28,0.12)]"
              role="dialog"
              aria-label={`Dictionary: ${popup.token}`}
            >
              <div className="flex items-baseline justify-between gap-3">
                <p className="font-book flex items-center gap-2 text-lg font-semibold">
                  {popup.entry?.word ?? popup.token.toLowerCase()}
                  <PlayButton src={popup.entry?.audio_word ?? null} label="Hear the word" />
                  {popup.entry?.pronunciation && (
                    <span className="text-ghost text-[12px] font-normal">/{popup.entry.pronunciation}/</span>
                  )}
                </p>
                <button onClick={() => setPopup(null)} aria-label="Close" className="text-ghost hover:text-ink -mr-1 px-1 text-sm">
                  ✕
                </button>
              </div>

              {popup.entry ? (
                <>
                  {popup.entry.meaning_en && (
                    <p className="font-book mt-2 text-[14px] leading-relaxed">{popup.entry.meaning_en}</p>
                  )}
                  {popup.entry.example_en && (
                    <p className="font-book text-ink-soft mt-1.5 flex items-start gap-2 text-[13px] italic">
                      <span>“{popup.entry.example_en}”</span>
                      <PlayButton
                        src={popup.entry.audio_example ?? null}
                        label="Hear the example"
                        size={12}
                        className="mt-0.5"
                      />
                    </p>
                  )}
                  {popup.entry.meaning_es &&
                    (esOpen ? (
                      <p lang="es" className="font-book text-cobalt-deep mt-2 text-[14px]">
                        {popup.entry.meaning_es}
                      </p>
                    ) : (
                      <button
                        onClick={() => setEsOpen(true)}
                        className="border-cobalt/40 text-cobalt-deep hover:bg-cobalt-wash mt-2.5 rounded-sm border border-dashed px-2.5 py-1 text-[10px] font-semibold tracking-[0.16em] uppercase transition-colors"
                      >
                        Uncover Spanish
                      </button>
                    ))}
                  <div className="border-rule mt-3 flex items-center gap-3 border-t pt-2.5">
                    {(['NEW', 'LEARNING', 'FAMILIAR', 'MASTERED'] as WordStatus[]).map((s) => (
                      <button
                        key={s}
                        onClick={() => setStatus(popup.entry!, s)}
                        className={`text-[10px] font-semibold tracking-[0.12em] uppercase ${
                          popup.entry!.status === s
                            ? 'text-cobalt-deep underline decoration-2 underline-offset-4'
                            : 'text-ghost hover:text-ink-soft'
                        }`}
                      >
                        {s.toLowerCase()}
                      </button>
                    ))}
                  </div>
                </>
              ) : (
                <>
                  <p className="font-book text-ink-soft mt-2 text-[14px] italic">
                    Not in your ledger yet.
                  </p>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => addToVocabulary(popup.token)}
                    className="mt-3"
                  >
                    Add to vocabulary
                  </Button>
                </>
              )}
            </motion.aside>
          )}
        </AnimatePresence>
      </div>

      {/* Sentence explanation — the "why is it built like that" panel */}
      <AnimatePresence>
        {explainIndex != null && (
          <motion.section
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={SLIDE}
            className="overflow-hidden"
          >
            <div className="border-cobalt/30 bg-cobalt-wash/40 mt-6 border-l-2 py-4 pr-4 pl-4">
              <div className="flex items-baseline justify-between gap-4">
                <p className="text-cobalt-deep text-[10px] font-semibold tracking-[0.2em] uppercase">
                  This sentence
                </p>
                <button
                  onClick={() => {
                    setExplainIndex(null)
                    setExplanation(null)
                  }}
                  className="text-ghost hover:text-ink text-sm"
                  aria-label="Close explanation"
                >
                  ✕
                </button>
              </div>
              {explaining && <Waiting>The coach is looking at it…</Waiting>}
              {!explaining && !explanation && (
                <ErrorLine>The coach could not explain this one — check the AI setup.</ErrorLine>
              )}
              {explanation && (
                <dl className="mt-2 space-y-2.5">
                  <Explained k="Means" v={explanation.meaning} />
                  <Explained k="Grammar" v={explanation.grammar} />
                  <Explained k="En español" v={explanation.spanish} lang="es" />
                  <Explained k="Watch out" v={explanation.watch_out} />
                </dl>
              )}
            </div>
          </motion.section>
        )}
      </AnimatePresence>

      {/* Comprehension quiz (generated readings) */}
      {text.questions && text.questions.length > 0 && (
        <ComprehensionQuiz textId={text.id} questions={text.questions} />
      )}

      <footer className="border-rule mt-6 flex items-center justify-between border-t pt-4">
        <p className="tnum text-ghost text-[12px]">
          {added.length > 0 && `${added.length} word${added.length === 1 ? '' : 's'} added this session`}
        </p>
        <Button variant="primary" onClick={finish}>
          Finish reading
        </Button>
      </footer>
    </Page>
  )
}

function Explained({ k, v, lang }: { k: string; v: string; lang?: string }) {
  return (
    <div className="flex flex-wrap gap-x-3">
      <dt className="text-cobalt-deep w-20 shrink-0 text-[10px] font-semibold tracking-[0.14em] uppercase">
        {k}
      </dt>
      <dd className="font-book text-ink-soft min-w-0 flex-1 text-[14px] leading-relaxed" lang={lang}>
        {v}
      </dd>
    </div>
  )
}

function Colophon({ k, v }: { k: string; v: string }) {
  return (
    <div className="border-rule flex justify-between gap-6 border-b py-2.5 text-[14px]">
      <dt className="text-ghost">{k}</dt>
      <dd className="text-right font-semibold">{v}</dd>
    </div>
  )
}

function fmtTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return m ? `${m} min ${s} s` : `${s} s`
}

function sentenceFor(body: string, token: string): string | undefined {
  const sentences = body.split(/(?<=[.!?])\s+/)
  const hit = sentences.find((s) => new RegExp(`\\b${token}\\b`, 'i').test(s))
  return hit?.trim().slice(0, 280)
}
