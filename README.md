# English OS

A local-first, single-user English learning app — spaced repetition (FSRS),
interactive reading with audio and shadowing, Duolingo/Busuu-style drills,
corrected writing and speaking, a two-host podcast generator, and analytics —
all backed by one SQLite file and a **Personal English Model** that decides
what you need to study next.

It runs entirely on your machine. The only network calls are optional: a
local LLM via [Ollama](https://ollama.com), or a cloud model (Anthropic /
Gemini) if you'd rather not run one yourself.

```
                         English OS (localhost)
   01 Today · 02 Vocabulary · 03 Reading · 04 Podcast · 05 Review
        · 06 Practice · 07 Writing · 08 Speaking · 09 Stats
                                   │
                        Personal English Model (app/model.py)
                                   │
                          SQLite  data/english.db
                                   │
                AIProvider → Ollama · Anthropic · Gemini
                                   │
                    faster-whisper (speech-to-text, local)
                    Kokoro / macOS `say` (text-to-speech, local)
```

## Features

| Lesson | What it does |
|---|---|
| **Today** | Your day as a single page: due cards, pending practice/writing/reading, error focus, streak and a recommended workload — with the reason behind it. |
| **Vocabulary** | A bilingual word ledger with FSRS states (NEW/LEARNING/FAMILIAR/MASTERED) and per-word pronunciation audio. |
| **Reading** | Paste a text or generate one constrained to your vocabulary. Tap any word for a translation, tap a sentence for a full breakdown, and shadow the audio at 0.8× speed. |
| **Podcast** | Two AI hosts discuss your vocabulary. Shadowing mode (highlighted transcript) or Ear-only mode (audio + comprehension quiz, no transcript). |
| **Review** | An FSRS-based SRS seeded from your real review history. Plan a session by time budget, not card count. |
| **Practice** | Multiple-choice drills: grammar for the day's tense, vocabulary gaps, and listening — one question at a time, corrected instantly. |
| **Writing** | One sentence at a time, corrected in seconds, building up to a full paragraph. Free writing is one click away. |
| **Speaking** | Answer prompts out loud → local transcription (faster-whisper) → categorized correction feeds back into your error history. |
| **Stats** | Evidence-based dashboards: reviews/day, vocabulary growth, retention, and where your recommended level actually comes from. |

Every mistake — in a drill, a writing, or something you said — lands in one
error table, which is what drives tomorrow's reading, drills, and grammar
tip.

Design rationale and the full decision log live in [DESIGN.md](DESIGN.md)
and [docs/adr/](docs/adr/).

## Tech stack

- **Backend**: Python, FastAPI, SQLite (schema in [app/db.py](app/db.py))
- **Scheduler**: [FSRS](https://github.com/open-spaced-repetition/py-fsrs)
- **Frontend**: React 19, TypeScript, Vite, Tailwind CSS
- **Speech-to-text**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (local, CPU)
- **Text-to-speech**: [Kokoro](https://github.com/hexgrad/kokoro) (local) or macOS `say`
- **LLM**: [Ollama](https://ollama.com) (local, default), with optional Anthropic/Gemini fallback

## Requirements

- macOS (uses `say` as a TTS fallback and an optional `launchd` agent — Linux/Windows can still run the dev server, just skip those two bits)
- Python 3.9+
- Node.js 18+
- [Ollama](https://ollama.com) — only if you want the AI features (reading generation, corrections, podcast) without a cloud API key

## Quickstart

### 1. Clone and install dependencies

```bash
git clone https://github.com/<your-username>/english-os.git
cd english-os

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

npm install --prefix frontend
```

### 2. Download the local model

The AI features (generated readings, writing corrections, the podcast
script) run on a local LLM through Ollama, so nothing you write leaves your
machine.

```bash
brew install ollama
brew services start ollama       # or: ollama serve
ollama pull qwen2.5:7b            # ~4.7 GB — swap for llama3.1:8b if you prefer
```

Speech-to-text (faster-whisper) and text-to-speech (Kokoro) download their
own small model weights automatically the first time you use Speaking or
Reading — no separate step needed.

### 3. Configure

```bash
cp .env.example .env
```

At minimum, set:

```bash
AI_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:7b
```

Everything else in `.env.example` (Notion IDs, cloud API keys) is optional —
the app works fully offline with just the two lines above. See
[app/ai.py](app/ai.py) for every provider and fallback chain it supports.

### 4. Run it

```bash
bash scripts/dev.sh
```

This starts FastAPI on `:8770` and Vite on `:5173`. Open
**http://localhost:5173**.

The database (`data/english.db`) is created empty on first run — there's no
seed vocabulary bundled with the repo. Add your first words from the
Vocabulary tab, or start a Reading/Practice session and the app will build
up your word list as you go.

### 5. (Optional) Install as a background app

```bash
scripts/install_app.sh
```

Installs a `launchd` agent that starts the app on login and adds an icon to
`~/Applications` you can drag to the Dock. The app is only reachable at
`127.0.0.1:8770` — never exposed to your network. Uninstall with
`scripts/install_app.sh uninstall`.

## Project structure

```
app/            FastAPI backend, SQLite schema, the Personal English Model
frontend/       React + TypeScript + Vite UI
scripts/        Install/dev scripts, one-off maintenance tools
docs/adr/       Architecture Decision Records — the "why" behind every pivot
tests/          Unit tests (python -m unittest discover tests)
DESIGN.md       Visual language, read before touching UI
```

## Status

This started as an Anki + Notion automation pipeline and evolved into a
local-first app once that pipeline's limits became clear — the full story
is in the ADRs, especially [ADR-006](docs/adr/ADR-006-english-os-local-first.md)
(the pivot), [ADR-011](docs/adr/ADR-011-anki-cutover.md) and
[ADR-012](docs/adr/ADR-012-notion-off.md) (turning the legacy integrations
off). Anki and Notion code paths still exist for historical reasons but are
inert — nothing in a fresh install touches either.

## License

No license file yet — all rights reserved by default until one is added.
Open an issue if you'd like to use this and I'll pick one.
