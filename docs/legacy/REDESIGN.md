# REDESIGN.md — Pedagogical engines spec

> ⚠️ **SUPERSEDED (2026-08-20)** por [ADR-006](docs/adr/ADR-006-english-os-local-first.md)
> (English Learning OS local-first, roadmap M0–M7). Ideas absorbidas: Motor 3 →
> Error Library (ADR-004, implementado), Motor 4 → M6 Speaking, Motor 5 → M7
> Analytics. Motor 1 (Input Engine) queda post-M7. Referencia histórica.

> Concrete implementation plan for the 5 engines proposed in PROJECT_UNDERSTANDING.md §3 (pedagogical analysis).
> Each engine is described as: **purpose · data flow · Notion schema needed · files · decisions blocked on the user (→ see BLOCKERS.md) · acceptance criteria**.

The current pipeline is preserved as the **legacy track** (Anki sync → Vocabulary Master → Writing Session / Reading page). The redesign **adds** five engines without breaking the legacy track. Migration is incremental — you can disable any legacy script at any time once its replacement is proven.

---

## Architecture at a glance

```
                       ┌─────────────────────────────────────┐
                       │  Shared core (already in repo)      │
                       │  scripts/notion_client.py           │
                       │  scripts/notion_blocks.py           │
                       │  run_all.py  (orchestrator + lock)  │
                       └─────────────────────────────────────┘
                                       ▲
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
┌───────────────┐  ┌──────────────────────────────┐  ┌──────────────────────────┐
│ M1 Input      │  │ M2 Sentence Mining           │  │ M3 Output / Errors      │
│ (listening)   │  │ (replaces 4000 Essential as  │  │ (free writing → errors  │
│               │  │  source of new vocab)        │  │  deck in Anki)          │
└───────────────┘  └──────────────────────────────┘  └──────────────────────────┘
        │                              │                              │
        └──────────────┬───────────────┴──────────────┬───────────────┘
                       ▼                              ▼
              ┌──────────────────┐         ┌──────────────────────┐
              │ M4 Speaking      │         │ M5 Dashboard         │
              │ (shadowing +     │         │ (weekly metrics +    │
              │  recording)      │         │  monthly probe)      │
              └──────────────────┘         └──────────────────────┘
```

All engines store state in Notion + Anki. The orchestrator (`run_all.py`) gains new modes (`input`, `dashboard`, …) that delegate to each engine.

---

## Motor 1 — Input Engine

**Purpose.** Replace AI-generated Reading stories with *real* native audio at i+1. Each session you drop a URL → the engine produces a transcript, extracts new vocabulary, and creates an Anki card with the original audio clipped around the target sentence.

### Data flow

```
1. User pastes URL  ───────────────►  Notion "Input Inbox" DB row (status=pending)
2. input_engine.py polls Inbox
3. yt-dlp downloads audio (mp3)
4. Whisper transcribes → JSON (segments with timestamps)
5. Tokenize transcript → identify words NOT in user's known vocab
6. For each new word, pick the sentence containing it + ±3s of audio
7. Create cloze Anki card via AnkiConnect (front: sentence with blank,
   back: word + meaning, audio attached)
8. Update Notion row: status=processed, n_words_extracted=K, transcript_url
```

### Notion schema (new DB: "Input Inbox")

| Property | Type | Notes |
|---|---|---|
| Title | title | URL or user-given name |
| URL | url | Source link |
| Source | select | YouTube / Podcast / Other |
| Duration (s) | number | Auto-filled |
| Status | select | pending / processing / done / failed |
| Words Extracted | number | Count of new cards generated |
| Transcript | rich_text or relation to a transcript page | Full or excerpt |
| Processed At | date | |
| Notes | rich_text | User free text |

### Files

- `scripts/motors/input_engine.py` — main orchestrator (poll inbox, process)
- `scripts/motors/transcribe.py` — Whisper wrapper (choose backend → BLOCKER)
- `scripts/motors/extractor.py` — tokenize, dedup against known vocab, pick sentences
- `scripts/motors/audio_clip.py` — ffmpeg helper to cut ±3s clips
- `scripts/motors/anki_card.py` — AnkiConnect addNote with cloze + audio

### Blocked on user

- **B-IN-1** Whisper backend: `openai-whisper` (local, slow on CPU, free) vs `faster-whisper` (3x faster, local, free) vs OpenAI API (paid, fastest). See BLOCKERS.md.
- **B-IN-2** Target deck name in Anki for the mined cards (new deck "English::Mined" recommended).
- **B-IN-3** Create the "Input Inbox" database in Notion (user creates, pastes ID into .env as INPUT_DB_ID).

### Acceptance criteria

- A URL pasted into Notion is processed within 5 min of running `python3 run_all.py input`.
- Each new word becomes a single Anki card with: cloze sentence, EN definition, audio playback button.
- Words already in `Vocabulary Master` are NOT re-added.
- A failure on one URL does not block the queue; status=failed with error message.

---

## Motor 2 — Sentence Mining

**Purpose.** Shift the source of new vocabulary from pre-made decks to **content you actually consumed**. Once you've crossed 3000 word families, every new word should come from real input.

### Data flow

```
Trigger 1: Motor 1 extracts a new word from listening
Trigger 2: User highlights a sentence in Notion (any source) and tags it #mine
Trigger 3: Reading session in Notion has a paragraph with [[brackets]] around new words
       │
       ▼
sentence_mining.py reads candidates
       │
       ▼
For each candidate sentence:
  • dedup against Vocabulary Master (skip if word already known)
  • build cloze: front = sentence with target word blanked
                  back  = target word + EN definition + (optional) ES gloss
  • optional: attach audio if source had it
       │
       ▼
Push to Anki via AnkiConnect addNotes(batch)
       │
       ▼
Insert row in Vocabulary Master with Source=mined, Provenance=<source URL>
```

### Notion schema additions (Vocabulary Master)

| New property | Type | Notes |
|---|---|---|
| Source | select (extend) | + values: `mined-listening`, `mined-reading`, `mined-manual` |
| Provenance | url | URL of the source content |
| Example Sentence | rich_text | The cloze front (full sentence) |
| Audio URL | url | If sourced from Motor 1 |

### Files

- `scripts/motors/sentence_mining.py` — entrypoint
- Reuses `extractor.py`, `anki_card.py`, `notion_client`

### Blocked on user

- **B-SM-1** Define the "known vocabulary" threshold: do we count any word that appears in Vocabulary Master regardless of state, or only those with state=`review` and reps≥3?
- **B-SM-2** Decide whether to keep the `Meaning (ES)` column at all. SLA recommendation: drop it for B2+ to break the translation crutch.

### Acceptance criteria

- A `#mine` tag in a Notion page becomes an Anki card within one run of the motor.
- Duplicates against Vocabulary Master are dropped (idempotent).
- Each mined card has: cloze front, back with definition, source link.

---

## Motor 3 — Output Engine (free writing + Errors deck)

**Purpose.** Replace fill-in-blank exercises with **free writing** under time pressure, automated correction, and *recycling of your own errors* as Anki cards. This is the highest-leverage SLA loop (Output Hypothesis + Noticing).

### Data flow

```
Daily prompt (chosen from your top 3 recurring error categories of the week):
  ┌──────────────────────────────────────────────┐
  │ "Write 10 minutes about X. No dictionary."   │
  └──────────────────────────────────────────────┘
       │
       ▼
User writes in Notion Writing Session page (existing DB)
       │
       ▼
output_engine.py is run (manually or scheduled):
  1. Fetch today's Writing Session page
  2. Locate the "Free Writing" block (paragraphs after a marker heading)
  3. Send to Claude API with a structured rubric:
        - Categorize errors: article, preposition, S-V agreement,
          collocation, tense, register, lexical choice, spelling
        - Return JSON: { corrections: [{original, fixed, category, explanation}],
                         c1_rewrite: "...",
                         lexical_diversity_score: 0-100 }
  4. Append blocks to Writing page:
        - "Errors today" callout with categorized list
        - "C1 reformulation" quote block
        - "Notice the gap" exercise (3 spots from c1_rewrite blanked)
  5. For each correction, push to Anki "English::Errors" deck:
        front: original sentence with the error word highlighted
        back:  fixed sentence + category + explanation
  6. Increment weekly counters in a NEW Notion DB "Error Categories"
        (so the dashboard can show top-5 recurring categories)
```

### Notion schema (new DB: "Error Categories")

| Property | Type | Notes |
|---|---|---|
| Title | title | "Articles", "Prepositions", … |
| Count This Week | number | Reset weekly by dashboard |
| Count All Time | number | Cumulative |
| Last Occurred | date | |
| Last Example | rich_text | Most recent erroneous sentence |

### Anki deck

- Name: `English::Errors`
- Card type: 2 fields (Front/Back), with extra `Category` tag for filtering.
- Created via AnkiConnect `addNote` with `tags=[category, "auto"]`.

### Files

- `scripts/motors/output_engine.py` — orchestrator
- `scripts/motors/claude_review.py` — Claude API wrapper with the rubric prompt
- `scripts/motors/error_recycler.py` — push errors to Anki + update Error Categories DB

### Blocked on user

- **B-OUT-1** Claude API key: get one at https://console.anthropic.com, add `ANTHROPIC_API_KEY=` to .env.
- **B-OUT-2** Confirm Anki deck name `English::Errors` (or pick your own).
- **B-OUT-3** Create the "Error Categories" Notion DB and add its ID to .env as ERRORS_DB_ID.
- **B-OUT-4** Decide on Claude model: `claude-opus-4-7` (best quality, $$$) vs `claude-sonnet-4-6` (recommended balance) vs `claude-haiku-4-5` (cheapest, lower correction quality).

### Acceptance criteria

- A free-writing block in today's Writing Session is processed within 30s of running `output_engine.py`.
- Each error becomes one Anki card; same error twice doesn't duplicate (look up by original sentence hash).
- Error Categories DB counters increment correctly.
- C1 reformulation appears in the Writing page.

---

## Motor 4 — Speaking Engine

**Purpose.** Train pronunciation and fluency, the two skills with the worst current coverage (zero).

### Data flow

**Sub-engine A — Shadowing tracker**
```
User selects an audio file (drops in `audio/shadow/today/` or pastes URL)
       │
       ▼
speaking_engine.py shadow start
  • plays audio
  • starts a timer that decrements after each loop
  • after N reps (default 10), logs to Notion "Shadowing Log"
```

**Sub-engine B — Recording + feedback**
```
User runs: speaking_engine.py record --topic "..." --seconds 120
       │
       ▼
  • prompts user, captures audio via sox or AVFoundation (mac)
  • Whisper transcribes
  • Claude API evaluates against rubric:
       - WPM (words per minute)
       - Errors per 100 words
       - Lexical band (% of words in NGSL 3K vs 5K vs 8K+)
       - Fluency notes (hesitations, fillers)
  • Pushes evaluation to Notion "Speaking Log" page
  • If errors > threshold, hand-off to error_recycler (Motor 3)
```

### Notion schemas

**New DB: "Shadowing Log"**
| Property | Type |
|---|---|
| Title | title (auto: source name) |
| Source URL | url |
| Reps Today | number |
| Total Reps | number |
| Last Practiced | date |

**New DB: "Speaking Log"**
| Property | Type |
|---|---|
| Title | title (auto: date + topic) |
| Date | date |
| Topic | rich_text |
| Duration (s) | number |
| WPM | number |
| Errors / 100 words | number |
| Lexical band (3K / 5K / 8K+) | rich_text |
| Audio path | rich_text (local file) |
| Transcript | rich_text |
| Feedback | rich_text |

### Files

- `scripts/motors/speaking_engine.py` — both sub-engines
- `scripts/motors/recorder.py` — platform-specific (macOS = `rec` via sox, or AVFoundation)
- `scripts/motors/lexical_band.py` — classify words against NGSL/COCA frequency lists
- Reuses `claude_review.py`, `transcribe.py`

### Blocked on user

- **B-SP-1** Install sox: `brew install sox`. Or pick another recorder.
- **B-SP-2** Create Shadowing Log and Speaking Log DBs in Notion. Add IDs to .env.
- **B-SP-3** Where to store audio files? `audio/` (in repo, gitignored) or `~/Documents/english_audio/`?
- **B-SP-4** Frequency list: NGSL 5K (recommended for B2→C1) or COCA top 5K?

### Acceptance criteria

- `speaking_engine.py shadow <url>` runs N reps and logs to Notion.
- `speaking_engine.py record` records, transcribes, scores, and creates a Speaking Log row in <90s for a 2-minute recording.

---

## Motor 5 — Dashboard

**Purpose.** Make progress visible. Today you have *activity* metrics ("Used Today" checkbox) but no *learning* metrics (recall rate, WPM, productive vocab). The dashboard is the feedback loop that lets every other engine self-tune.

### Data flow

```
Run weekly (Sunday night) or on demand:
       │
       ▼
dashboard.py gathers:
  • Vocab: total, this week added, this week retained at 7d
  • Listening: minutes/week from Input Inbox + Shadowing Log
  • Speaking: minutes/week + average WPM trend from Speaking Log
  • Reading: WPM from latest WPM test (probe), total reading minutes
  • Writing: words produced/week from Writing Sessions
  • Errors: top 5 categories of the week + delta vs last week
  • Productive recall: weekly probe (20 random words ES→EN test)
       │
       ▼
Writes/updates a Notion "Weekly Dashboard" page
  • Pretty Markdown-style block layout
  • Sparkline-equivalent: small inline charts via text bars
  • Diff vs last week (↑ / ↓ / →)
       │
       ▼
At end of month, schedules a Probe (EFSET or Cambridge sample) reminder
```

### Notion schema (new DB: "Weekly Dashboards")

| Property | Type |
|---|---|
| Title | title (auto: ISO week, e.g., "Week 2026-W22") |
| Week Start | date |
| Vocab Added | number |
| Vocab Retained 7d | number |
| Listening Min | number |
| Speaking Min | number |
| Reading WPM | number |
| Writing Words | number |
| Top Error #1 | rich_text |
| Top Error #2 | rich_text |
| Top Error #3 | rich_text |
| Productive Recall % | number |

### Files

- `scripts/motors/dashboard.py` — main aggregator
- `scripts/motors/probe.py` — productive recall probe (CLI quiz, 20 words)

### Blocked on user

- **B-DA-1** Confirm running schedule (Sunday 21:00? End of last study session of the week?).
- **B-DA-2** Create Weekly Dashboards DB in Notion. Add ID to .env.

### Acceptance criteria

- `python3 run_all.py dashboard` produces a Notion page summarizing the week.
- All counters are populated from real data (not placeholders) once the upstream engines have data.
- Probe runs in CLI: shows 20 words, scores, writes result to dashboard.

---

## Sequencing recommendation

I would build in this order (highest leverage first, fewest blockers):

| Order | Motor | Why | External blockers |
|---|---|---|---|
| 1 | **M3 Output** | Best ROI on what you already write; reuses existing Writing DB | Claude API key, deck name |
| 2 | **M5 Dashboard** | Makes progress measurable; needed to validate later motors | Just a DB |
| 3 | **M1 Input** | Highest pedagogical leverage but heaviest tooling (Whisper, ffmpeg, yt-dlp) | Whisper choice, ffmpeg, DB |
| 4 | **M2 Sentence Mining** | Natural extension of M1 + your existing Vocab DB | Trivial once M1 exists |
| 5 | **M4 Speaking** | Critical skill but most platform-dependent (recording) | sox, DB, frequency list |

---

## Non-goals (what this redesign explicitly does NOT do)

- Replace Anki as the SRS engine. Anki stays.
- Move data out of Notion. Notion stays as the dashboard/UI.
- Generate B1 stories with AI. The Reading page generator is deprecated once Motor 1 ships.
- Translate every word to Spanish. Only kept for first occurrence under B2; dropped for sentence-mined cards.
- Build a custom mobile app. Notion + Anki mobile already cover this.

---

## Open architectural questions

These don't block the first sprint but are worth deciding before too many engines are wired up:

1. **One Claude API key or per-engine?** Recommendation: one key, billed centrally, scoped via system prompt per call.
2. **Where do audio clips live for cloze cards?** Anki copies media into its own collection.media folder, so the source can be ephemeral. But for re-use across Notion (preview), we'd need a stable URL.
3. **Sync engines on the same lockfile as legacy?** Recommendation: yes — same `run_all.py` orchestrator, same lockfile, just new modes.
4. **Schedule (cron / launchd)?** Dashboard and Input Engine benefit from scheduled runs. Can use `launchd` on macOS.
