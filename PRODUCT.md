# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

React + TypeScript + Tailwind v4 + Motion (Vite) in `frontend/`, over a local
FastAPI + SQLite backend (`app/server.py`, `data/english.db`). Local-first:
runs on Eddie's Mac at localhost; no auth, no multi-tenancy. (User-decided,
ADR-006 D2.)

## Users

One user: Eddie — Spanish speaker (Mexico City), A2/B1 English moving to
B2/C1 over ~2 years. Frontend engineer at Clip (Mexican fintech):
technically fluent, reads UI with a practitioner's eye, strong interest in
product. Studies ~60–75 min in the mornings on a Mac. High current
motivation, but the system
must survive low-motivation months (habit guardrail: ≥5 sessions/week).
L1 interference is Spanish: articles, prepositions, word order, false friends.
Interaction preference (observed, binding for UX): he abandons activities
that demand a lot of writing. Multiple choice, toggles and a single short
written answer work; long free production does not (last writing saved in
the app: 2026-08-24, 31 words; last produced text of any kind: 2026-08-27).

## Product Purpose

"English OS": a personal English-learning app that combines spaced repetition
(FSRS in-app), LingQ-style interactive reading, an AI tutor
(generation + correction), speaking practice, and real progress analytics —
all feeding one Personal English Model. Success = measurable level progress
(errors/100 words trending down, external probes), not engagement.

## Positioning

Unlike Duolingo/Anki/tutors: it observes what Eddie *produces* (writing,
speaking), keeps a structured model of his recurring errors and vocabulary
states, and every generator consumes that model — content deliberately reuses
what he is learning. Its only success metric is his real English level; there
is no engagement conflict of interest.

## Operating Context

- Daily loop today: open Today → a Review sitting (FSRS in-app) → closing
  the sitting (`session.end` → `jobs.enqueue_daily`) queues the day's
  reading, activities and tip → read / practice / write / speak in the app.
  `data/english.db` is the only source of truth.
- Legacy pipeline is off: Anki frozen 2026-08-21 (ADR-011), Notion off
  2026-08-21 (ADR-012; any write raises `NotionOff`). Neither is a mirror.
- Vocabulary came from the "AJ-Basic" Anki deck (Word, Meaning ES,
  Example_en, Example_es, IPA) and now lives only in SQLite; states
  NEW / LEARNING / FAMILIAR / MASTERED.
- AI is local: Ollama `llama3.1:8b` on a 16 GB Mac, 15–80 s per response.
  Waiting states are a central part of the experience, not a detail: the
  user must understand what is happening and be able to do something else
  meanwhile. Anthropic is an optional provider.

## Capabilities and Constraints

- Built (M1–M22), ten lessons in the rail: 01 Today, 02 Vocabulary,
  03 Reading (+ Reader: tap-a-word, ¶ sentence explanation, listen & shadow,
  comprehension quiz), 04 Podcast, 05 Review (FSRS), 06 Practice,
  07 Writing (guided, one sentence at a time), 08 Speaking (+ spoken
  conversation), 09 Shadowing (over video), 10 Stats.
- Background jobs queue AI work (`/api/jobs`); a paused course
  (`/api/pause`) freezes the queue without breaking the streak.
- UI chrome language: **English** (immersion; user-confirmed). Spanish
  translations render **only on demand** (tap/hover), pushing recall in
  English first (user-confirmed; Vision principle P1).
- Terminology: word statuses are NEW, LEARNING, FAMILIAR, MASTERED; error
  categories [ART] [PREP] [S-V] [COLL] [TENSE] [REG] [WORD].
- No gamified pressure (punitive streaks, leagues) — binding no-goal.
- Accuracy metrics with <150 words produced in window must show
  "not enough data", never an invented number.

## Brand Commitments

Name in use: "English OS". Aesthetic constraint (user-stated, binding):
must feel like a focused learning/reading application — Kindle, LingQ,
Readwise Reader, Anki — and explicitly NOT a generic SaaS/admin dashboard.
No other visual identity exists yet.

## Evidence on Hand

Real data in `data/english.db` (read 2026-09-15): 3,104 words
(2,859 NEW · 121 LEARNING · 111 FAMILIAR · 13 MASTERED), 1,771 reviews
(1,050 from Anki + 721 FSRS in-app since 2026-08-21), 54 categorized errors,
38 study sittings (2–4 distinct days/week so far, under the ≥5 guardrail),
100 readings, 78 writings (77 Notion-era, 1 in the app), 10 podcasts,
4 speaking texts, 48 activities, 6 conversations, 2 shadowing sessions.
No invented testimonials/pricing/benchmarks apply (single-user tool).

## Product Principles

1. Production over recognition — every design choice should push Eddie to
   produce/recall English, not just recognize it.
2. Data as by-product — no metric may require manual logging.
3. One brain — modules read/write the same Personal English Model.
4. Evidence over sensation — difficulty and progress claims come from
   windowed metrics, never vibes.
5. Simplest thing that teaches — features that don't teach get cut.
