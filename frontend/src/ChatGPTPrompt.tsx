import { useEffect, useState } from 'react'
import { api } from './api'
import type { StudiedWord } from './api'
import { Button, Section } from './ui'

/* Un prompt para practicar fuera de la app (ChatGPT, modo voz o texto) con las
   palabras que tocaste hoy. Las falladas van primero: son las que más necesitan
   salir en contexto. */
type Mode = 'speaking' | 'writing'

const MAX_WORDS = 20

function wordLine(w: StudiedWord) {
  const gloss = w.meaning_en || w.meaning_es
  return `- ${w.word}${gloss ? ` — ${gloss}` : ''}${w.worst_rating === 1 ? ' (I struggled with this one)' : ''}`
}

const COMMON = `You are my English tutor. I'm a Spanish speaker at B1 level working toward B2/C1.
Today I studied these words (hardest ones first):

{WORDS}

Rules:
- Use these words naturally and push me to use them too. Keep track and, at the end, tell me which ones I used correctly, which ones I misused, and which ones I never used.
- Correct at most 3 mistakes per turn. For each: what I said → the correct version → one short line of why. Tag it as [ART], [PREP], [S-V], [COLL], [TENSE], [REG] or [WORD].
- Keep your own language at B1–B2. If I get stuck, give me a hint, not the answer.
- When I say "finish", give me: a summary of word usage, my 3 most repeated mistakes, 1 concrete strength and 1 specific thing to practice.`

const MODES: Record<Mode, { label: string; hint: string; task: string }> = {
  speaking: {
    label: 'Or talk with ChatGPT voice',
    hint: 'Paste it in a new ChatGPT chat, send it, then tap the voice button and start talking.',
    task: `Mode: SPOKEN CONVERSATION. I'm using ChatGPT voice mode, so everything happens out loud.
- Start by proposing 3 realistic, everyday topics where these words fit; I'll pick one.
- Keep your turns short (2–3 sentences) and always end with a question so I do most of the talking.
- Don't interrupt me to correct. Give corrections at natural pauses, spoken briefly (skip the tags out loud).
- Tell me if a word I used sounds unnatural when spoken, and model the right pronunciation if I stumble.
- Every 4–5 turns, ask me a question that forces me to use one of the words I haven't used yet.`,
  },
  writing: {
    label: 'Or write with ChatGPT',
    hint: 'Paste it in a new ChatGPT chat and write your answers there.',
    task: `Mode: WRITING.
1. Give me a short, realistic writing task (80–120 words: an email, a message, an opinion) where I must use at least 5 of the words.
2. When I send it, correct it with the rules above, then show me a B2 version of my text with the words kept.
3. Then give me a second task with the words I didn't use. Repeat until I say "finish".`,
  },
}

function buildPrompt(mode: Mode, words: StudiedWord[]) {
  const sorted = [...words].sort((a, b) => a.worst_rating - b.worst_rating).slice(0, MAX_WORDS)
  return `${COMMON.replace('{WORDS}', sorted.map(wordLine).join('\n'))}\n\n${MODES[mode].task}`
}

export default function ChatGPTPrompt({ mode }: { mode: Mode }) {
  const [words, setWords] = useState<StudiedWord[] | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    api.studiedToday().then((d) => setWords(d.items)).catch(() => setWords([]))
  }, [])

  if (!words) return null
  const prompt = buildPrompt(mode, words)

  const copy = async () => {
    await navigator.clipboard.writeText(prompt)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Section label={MODES[mode].label}>
      {words.length === 0 ? (
        <p className="font-book text-ink-soft mt-2 text-[14px] italic">
          No words studied today yet — do a Review session first.
        </p>
      ) : (
        <>
          <p className="font-book text-ink-soft mt-2 max-w-[64ch] text-[14px]">
            A prompt with today's {Math.min(words.length, MAX_WORDS)} words — runs in ChatGPT, not on
            this computer. {MODES[mode].hint}
          </p>
          <div className="mt-3 flex items-center gap-4">
            <Button size="sm" onClick={copy}>
              {copied ? 'Copied' : 'Copy prompt'}
            </Button>
            <a
              href="https://chatgpt.com/"
              target="_blank"
              rel="noreferrer"
              className="text-cobalt-deep hover:text-cobalt text-[11px] font-semibold tracking-[0.14em] uppercase"
            >
              Open ChatGPT ↗
            </a>
          </div>
          <details className="mt-3">
            <summary className="text-ghost cursor-pointer text-[12px]">See prompt</summary>
            <pre className="font-ui text-ink-soft mt-2 text-[12px] whitespace-pre-wrap">{prompt}</pre>
          </details>
        </>
      )}
    </Section>
  )
}
