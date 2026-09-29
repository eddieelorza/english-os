export type WordStatus = 'NEW' | 'LEARNING' | 'FAMILIAR' | 'MASTERED'
export type WordKind = 'word' | 'phrasal_verb' | 'expression' | 'sentence'

export interface Word {
  id: number
  word: string
  kind: WordKind
  status: WordStatus
  cefr: string | null
  meaning_en: string | null
  meaning_es: string | null
  pronunciation: string | null
  example_en: string | null
  example_es: string | null
  source: string | null
  deck: string | null
  audio_word: string | null
  audio_example: string | null
  image_path: string | null
  ease: number | null
  interval_days: number | null
  lapses: number | null
  review_count: number | null
  times_used: number
  last_reviewed_on: string | null
}

export interface Review {
  reviewed_at: string
  rating: number
  interval_days: number | null
  review_kind: string
}

export interface WordDetail extends Word {
  reviews: Review[]
}

export interface WordPage {
  total: number
  page: number
  per_page: number
  items: Word[]
}

export interface Summary {
  words: Record<WordStatus, number>
  words_total: number
  reviews_14d: number
  top_error_categories: string[]
  last_session: Record<string, unknown> | null
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    /* FastAPI puts the real cause in `detail` ("AIUnavailable: Ollama is not
       running…"). Throwing only "503 Service Unavailable" is why every screen
       could say no more than "check the AI setup": the sentence that named
       the problem was being discarded here. */
    let detail = ''
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* not JSON, or already consumed — the status line still tells us something */
    }
    throw new Error(detail || `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export interface TextSummary {
  id: number
  title: string
  date: string | null
  level: string | null
  topic: string | null
  source: string | null
  reading_seconds: number | null
  finished_at: string | null
  word_count: number
}

export interface LexiconEntry {
  id: number
  word: string
  normalized: string
  status: WordStatus
  kind: WordKind
  meaning_en: string | null
  meaning_es: string | null
  pronunciation: string | null
  example_en: string | null
  review_count: number | null
  interval_days: number | null
  audio_word?: string | null
  audio_example?: string | null
}

export interface NarrationMark {
  text: string
  start: number
  end: number
}

export interface Question {
  /* Readings call it `question`; activities call it `prompt`. */
  question?: string
  prompt?: string
  options: string[]
  answer_index: number
  why: string
  category?: string
  audio?: string | null
}

export interface TextDetail {
  id: number
  title: string
  date: string | null
  level: string | null
  topic: string | null
  source: string | null
  body: string
  questions: Question[] | null
  words_target: string[] | null
  reading_seconds: number | null
  finished_at: string | null
  lexicon: Record<string, LexiconEntry>
}

export interface StudiedWord extends Word {
  card_state: CardState | null
  /* Lowest rating given today: 1 means it was failed at least once. */
  worst_rating: number
  times: number
  last_at: string
  introduced: number
}

export interface StudiedToday {
  date: string
  total: number
  introduced: number
  struggled: number
  items: StudiedWord[]
}

export interface ReviewCard {
  id: number
  word: string
  pronunciation: string | null
  meaning_en: string | null
  meaning_es: string | null
  example_en: string | null
  example_es: string | null
  status: WordStatus
  is_new: boolean
  /* ADR-014: a word the triage gave up for lost, coming back at a trickle. */
  comeback?: boolean
  audio_word: string | null
  audio_example: string | null
  image_path: string | null
}

export type CardState = 'NEW' | 'LEARNING' | 'REVIEW' | 'RELEARNING'
export type RatingName = 'again' | 'hard' | 'good' | 'easy'

export interface RatingOutcome {
  rating: 1 | 2 | 3 | 4
  seconds: number
  /* Anki-style label: "1m", "10m", "3d", "2.1mo". */
  interval: string
  due: string
  state_after: CardState
  step_after: number | null
  graduates: boolean
}

export interface SchedulePreview {
  word_id: number
  state: CardState
  step: number | null
  /* False when fuzzing is on: the numbers become estimates. */
  exact: boolean
  ratings: Record<RatingName, RatingOutcome>
}

export interface ReviewQueue {
  /* Due cards this sitting may still show (capped by the session plan). */
  due: number
  /* Due cards in reality, cap ignored. */
  due_total: number
  new_available: number
  /* Everything still on the learning ladder, due or not. */
  learning: number
  /* Only the ones due by the clock right now. */
  learning_now: number
  /* Cards still on the ladder but answered too recently to show again: a step
     measures elapsed time, so answering one two seconds later proves nothing. */
  cooling: number
  /* When the first of those comes back (local ISO). Null if none is waiting. */
  resume_at: string | null
  introduced_today: number
  reviewed_today: number
  next: ReviewCard | null
  /* The four intervals for `next`. Null if it could not be computed — the
     buttons lose their numbers but the card is still answerable. */
  preview: SchedulePreview | null
  preview_error?: string
  /* ADR-014: the sitting is going badly, so due and new cards stopped. Only
     the words in progress are still served. Null when all is well. */
  brake?: { on: boolean; reviews: number; again: number; rate: number; note: string } | null
  /* True when `next` is a learning card shown ahead of its step. */
  ahead: boolean
  paused?: boolean
  session?: SessionProgress
}

export interface Pace {
  seconds_per_card: number
  seconds_per_new: number
  samples: number
  measured: boolean
  note: string | null
}

export interface SessionPlan {
  mode: SessionMode
  minutes: number | null
  new: number
  reviews: number
  total: number
  estimated_minutes: number
  pace: Pace
  available: { new: number; reviews: number }
  short: string[]
  paused: boolean
  /* ADR-014: what is today's and what gets scheduled once you sit down. */
  triage?: { due: number; today: number; later: number; days: number; comeback: number }
  /* ADR-015 (auto mode): the limit is ANSWERS, repeats included. `why` is the
     evidence behind the number, in short lines. Null/absent in other modes;
     in auto with too little history `why` explains the fallback to time. */
  budget?: number
  day_budget?: number
  answered_today?: number
  why?: string[] | null
  less?: boolean
  gate?: { new_per_day: number; ceiling: number; code: string; reason: string | null }
}

export interface SessionProgress {
  active: boolean
  id?: number
  started_at?: string
  mode?: SessionMode
  minutes?: number | null
  planned_new?: number
  planned_reviews?: number
  done_new?: number
  done_reviews?: number
  remaining_new?: number
  remaining_reviews?: number
  done?: number
  planned?: number
  /* Auto mode: the sitting's limit in answers. Null otherwise. */
  budget?: number | null
}

export interface Projection {
  new_per_day: number
  reviews_per_word: { value: number; words: number; measured: boolean }
  steady_daily_reviews: number
  capacity: number
  sustainable: boolean
  note: string | null
}

export interface BacklogStatus {
  due: number
  capacity: number
  excess: number
  overloaded: boolean
  spread_days: number
  projection: Projection
  lateness: {
    window_days: number
    reviews: number
    avg_days_late: number | null
    worst_days_late: number | null
    enough: boolean
  }
  spread_today: { date: string; cards: number; days: number; kept_today: number } | null
}

export interface SpreadResult {
  spread: boolean
  cards?: number
  days?: number
  kept_today?: number
  capacity?: number
  /* Cards per day the spread had to use. Above `capacity` when the backlog
     does not fit the horizon. */
  per_day?: number
  over_capacity?: boolean
  comeback?: number
  comeback_today?: number
}

export type SessionMode = 'time' | 'counts' | 'auto'

export interface Settings {
  mode: SessionMode
  minutes: number
  new: number
  reviews: number
  new_per_day: number
}

export interface ReviewAnswerResult {
  word_id: number
  status: WordStatus
  interval_days: number
  due: string
  introduced: boolean
  queue: ReviewQueue
  /* El progreso de la sentada viaja con la respuesta (`/api/review/answer` lo
     devuelve) para que el contador de la cabecera no necesite otra petición.
     Faltaba en el tipo y `tsc -b` rompía la build de producción. */
  session: SessionProgress | null
}

export interface ActiveConversation {
  id: number
  topic: string | null
  turns: number
  started_at: string
}

export interface ConversationOpening {
  conversation_id: number
  reply: string
  audio: string | null
  marks?: { text: string; start: number; end: number }[]
}

export interface ConversationTurn {
  you_said: string
  seconds: number | null
  reply: string
  audio: string | null
}

export interface ConversationCorrection {
  category: string
  original: string
  correction: string
  explanation: string
}

export interface ConversationSummary {
  conversation_id: number
  turns?: number
  spoken_seconds?: number
  corrections: ConversationCorrection[]
  strength: string
  already_closed?: boolean
}

export interface ShadowLine {
  id: number
  idx: number
  start_s: number
  end_s: number
  text: string
  confidence: number | null
  done_at: string | null
}

export interface ShadowSession {
  id: number
  url: string
  title: string | null
  channel: string | null
  seconds: number | null
  audio_path: string | null
  /* Media de `avg_logprob`: > -0.5 fiable, <= -0.8 poco de fiar. Se enseña
     para no presentar una transcripción dudosa como si fuera cierta. */
  confidence: number | null
  lines: ShadowLine[]
  done: number
}

export interface ShadowSummary {
  id: number
  title: string | null
  channel: string | null
  seconds: number | null
  confidence: number | null
  date: string
  lines: number
  done: number
}

export interface ShadowCreated {
  ready: boolean
  session?: ShadowSession
  job_id?: number
  title?: string
  seconds?: number
}

export interface LevelRecommendation {
  level: string
  reason: string
  evidence?: string[]
}

export interface EvidenceSource {
  label: string
  value: number | null
  display: string | null
  n: number
  unit: string
  enough: boolean
  signal: 'consolidate' | 'hold' | 'stretch' | null
}

export interface Evidence {
  window_days: number
  recall: EvidenceSource
  comprehension: EvidenceSource
  controlled: EvidenceSource
  production: EvidenceSource
}

export interface ModelSnapshot {
  date: string
  vocabulary: { counts: Record<WordStatus, number>; total: number }
  learning_words: string[]
  errors: {
    window_days: number
    top_categories: string[]
    words_produced: number
    errors_total: number
    errors_per_100: number | null
    enough_data: boolean
  }
  review: { window_days: number; reviews: number; again_rate: number | null; fsrs_reviews: number }
  reading: { window_days: number; minutes: number; texts_finished: number }
  streak_days: number
  recommendation: LevelRecommendation
}

export interface PauseState {
  paused: boolean
  since: string | null
  days: number
  reason: string | null
}

export interface ResumeResult {
  resumed: boolean
  days_paused?: number
  cards_spread?: number
  ramp_days?: number
  anki?: { reachable: boolean; cards: number }
}

export interface Today {
  date: string
  pause: PauseState
  recommendation: LevelRecommendation
  review: Omit<ReviewQueue, 'next'>
  last_session: {
    date: string
    cards_reviewed: number | null
    again_rate: number | null
  } | null
  reading_minutes_today: number
  unfinished_reading: { id: number; title: string; level: string | null } | null
  error_focus: string[]
  /* Words you keep reviewing that are not moving. */
  stuck_words: {
    word: string
    meaning_es: string | null
    lapses: number
    review_count: number
    interval_days: number
    difficulty: number
  }[]
  stuck_total: number
  streak_days: number
}

export interface SpeakingError {
  original: string
  correction: string
  category: string
  explanation: string
}

export interface SpeakingResult {
  id: number
  transcript: string
  duration_seconds: number
  words_produced: number
  errors: SpeakingError[]
  natural_version: string
  strength: string
  practice_next: string
  speaking_minutes_today: number
}

export interface Stats {
  totals: {
    words_known: number
    mastered: number
    vocabulary: Record<WordStatus, number>
    reviews_all_time: number
    texts_read: number
    speaking_sessions: number
    streak_days: number
  }
  recommendation: LevelRecommendation
  evidence: Evidence
  review_7d: { reviews: number; again_rate: number | null }
  errors_14d: { errors_per_100: number | null; enough_data: boolean }
  lateness: {
    summary: {
      window_days: number
      reviews: number
      avg_days_late: number | null
      worst_days_late: number | null
      enough: boolean
    }
    by_bucket: { label: string; reviews: number; recall: number | null; enough: boolean }[]
    weekly: { week_start: string; reviews: number; avg_days_late: number | null }[]
    spreads: { window_days: number; times: number; cards: number }
    min_sample: number
  }
  daily: { date: string; reviews: number; reading_minutes: number; speaking_minutes: number }[]
  weekly: {
    week_start: string
    introduced: number
    cumulative: number
    reviews: number
    retention: number | null
  }[]
}

export interface Activity {
  id: number
  date: string
  kind: 'grammar_quiz' | 'vocabulary_check' | 'listening'
  title: string
  questions: Question[]
  score: number | null
  total: number | null
  answers: number[] | null
  completed_at: string | null
}

export interface GrammarTip {
  category: string
  rule: string
  wrong: string
  right: string
  remember: string
}

export interface WritingStep {
  /* What this sentence should say, in Spanish. */
  ask: string
  /* The first few English words, so the box is never blank. */
  starter: string
  word: string
}

export interface WritingTask {
  scenario: string
  from_name: string
  message: string
  steps: WritingStep[]
  focus: string
}

export interface SentenceCheck {
  ok: boolean
  fixed: string
  note: string
  category?: string
}

/* One answered step, carried to the finish call. */
export interface WrittenSentence extends SentenceCheck {
  text: string
}

export interface GuidedResult {
  id: number
  words_produced: number
  seconds: number
  sentences: number
  errors: SpeakingError[]
  improved_version: string
  strength: string
  practice_next: string
}

export interface WritingResult {
  id: number
  words_produced: number
  seconds: number
  focus: string
  errors: SpeakingError[]
  improved_version: string
  tenses_used: string[]
  focus_hit: boolean
  focus_note: string
  strength: string
  practice_next: string
}

export interface SentenceExplanation {
  sentence: string
  meaning: string
  grammar: string
  spanish: string
  watch_out: string
  cached: boolean
}

export interface LibraryDay {
  date: string
  reading: {
    id: number
    title: string
    level: string | null
    topic: string | null
    finished: boolean
    narrated: boolean
    generated: boolean
  }[]
  writing: { id: number; title: string; words_produced: number | null; errors_count: number | null }[]
  speaking: { id: number; title: string; words_produced: number | null; errors_count: number | null }[]
  activities: {
    id: number
    kind: string
    title: string
    score: number | null
    total: number | null
    completed: boolean
  }[]
}

export interface PodcastSummary {
  id: number
  title: string
  date: string | null
  level: string | null
  finished: boolean
}

export interface Episode {
  id: number
  title: string
  date: string | null
  level: string | null
  topic: string | null
  speakers: { A: string; B: string }
  turns: { speaker: 'A' | 'B'; text: string }[]
  questions: Question[]
  words_target: string[]
  audio: string
  marks: (NarrationMark & { turn: number; speaker: 'A' | 'B' })[]
  finished_at: string | null
  seconds: number | null
}

export interface AIStatus {
  configured: boolean
  provider: string | null
  model: string | null
  anthropic_available: boolean
  ollama_running: boolean
  ollama_models: string[]
}

export interface GenerateResult {
  id: number
  title: string
  word_count: number
  target_words: string[]
  missing_words: string[]
  provider: string
  model: string
}

export type JobKind =
  | 'reading'
  | 'podcast'
  | 'activities'
  | 'tip'
  | 'writing_task'
  | 'shadow'
export type JobStatus = 'queued' | 'running' | 'done' | 'failed'

export interface Job {
  id: number
  kind: JobKind
  params: Record<string, unknown>
  status: JobStatus
  result: Record<string, never> | Record<string, string | number | string[]> | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  /* How many jobs are queued or running, this one included. */
  pending?: number
}

/* What `session.end` queued — job ids, or the reason it could not ask. */
export interface Material {
  queued?: number[]
  reading_skipped?: boolean
  error?: string
}

export const api = {
  summary: () => request<Summary>('/api/summary'),

  enqueue: (kind: JobKind, params?: Record<string, unknown>) =>
    request<Job>('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, params: params ?? {} }),
    }),

  job: (id: number) => request<Job>(`/api/jobs/${id}`),

  jobs: () => request<{ jobs: Job[]; pending: number }>('/api/jobs'),

  words: (opts: {
    q?: string
    status?: WordStatus | ''
    sort?: string
    page?: number
    perPage?: number
  }) => {
    const p = new URLSearchParams()
    if (opts.q) p.set('q', opts.q)
    if (opts.status) p.set('status', opts.status)
    if (opts.sort) p.set('sort', opts.sort)
    p.set('page', String(opts.page ?? 1))
    p.set('per_page', String(opts.perPage ?? 50))
    return request<WordPage>(`/api/words?${p}`)
  },

  studiedToday: () => request<StudiedToday>('/api/words/studied-today'),

  word: (id: number) => request<WordDetail>(`/api/words/${id}`),

  patchWord: (id: number, patch: Partial<Pick<Word, 'status' | 'cefr'>>) =>
    request<WordDetail>(`/api/words/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),

  addWord: (w: { word: string; status?: WordStatus; example_en?: string }) =>
    request<Word>('/api/words', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(w),
    }),

  texts: () => request<{ items: TextSummary[] }>('/api/texts'),

  createText: (t: { title?: string; body: string }) =>
    request<{ id: number; title: string; word_count: number }>('/api/texts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(t),
    }),

  text: (id: number) => request<TextDetail>(`/api/texts/${id}`),

  reviewQueue: () => request<ReviewQueue>('/api/review/queue'),

  reviewAnswer: (wordId: number, rating: 1 | 2 | 3 | 4) =>
    request<ReviewAnswerResult>('/api/review/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ word_id: wordId, rating }),
    }),

  sessionPlan: (opts: {
    mode?: SessionMode
    minutes?: number
    new?: number
    reviews?: number
    less?: boolean
  }) => {
    const p = new URLSearchParams()
    if (opts.less != null) p.set('less', String(opts.less))
    if (opts.mode) p.set('mode', opts.mode)
    if (opts.minutes != null) p.set('minutes', String(opts.minutes))
    if (opts.new != null) p.set('new', String(opts.new))
    if (opts.reviews != null) p.set('reviews', String(opts.reviews))
    return request<{ plan: SessionPlan; settings: Settings; session: SessionProgress }>(
      `/api/session/plan?${p}`,
    )
  },

  sessionStart: (opts: {
    mode?: SessionMode
    minutes?: number
    new?: number
    reviews?: number
    less?: boolean
  }) =>
    request<SessionProgress & { plan: SessionPlan }>('/api/session/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts),
    }),

  /* Closing the sitting is what queues the day's material (ADR-011), so the
     answer carries it. The screen used to drop `material` on the floor: the
     reading, the drill and the message were being written and nothing said
     so. */
  sessionEnd: () =>
    request<
      SessionProgress & { ended: boolean; backlog?: SpreadResult; material?: Material }
    >('/api/session/end', { method: 'POST' }),

  /* "Study more": brings the next scheduled cards forward to today. */
  pullForward: (cards = 20) =>
    request<{ pulled: number; asked: number }>('/api/backlog/pull', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cards }),
    }),

  /* ADR-015 "study more": adds answers to TODAY only; never a preference. */
  loadMore: (answers = 20) =>
    request<{ extra: number; pulled: number }>('/api/load/more', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answers }),
    }),

  /* The fail brake is advice, not a lock: this releases it for the sitting. */
  keepGoing: () => request<{ released: boolean }>('/api/session/keep-going', { method: 'POST' }),

  backlog: (newPerDay?: number) =>
    request<BacklogStatus>(
      `/api/backlog${newPerDay != null ? `?new_per_day=${newPerDay}` : ''}`,
    ),

  settings: () => request<Settings>('/api/settings'),

  patchSettings: (patch: Partial<Settings>) =>
    request<Settings>('/api/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),

  today: () => request<Today>('/api/today'),

  model: () => request<ModelSnapshot>('/api/model'),

  pauseState: () => request<PauseState>('/api/pause'),

  pauseStart: (reason: string) =>
    request<PauseState>('/api/pause', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    }),

  pauseResume: () => request<ResumeResult>('/api/pause/resume', { method: 'POST' }),

  stats: () => request<Stats>('/api/stats'),

  podcasts: () => request<{ items: PodcastSummary[] }>('/api/podcasts'),

  podcast: (id: number) => request<Episode>(`/api/podcasts/${id}`),

  createPodcast: (opts: { minutes: number; topic: string }) =>
    request<Episode>('/api/podcasts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts),
    }),

  finishPodcast: (id: number, seconds: number) =>
    request<{ listening_minutes_today: number }>(`/api/podcasts/${id}/finish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seconds }),
    }),

  explain: (sentence: string, textId?: number) =>
    request<SentenceExplanation>('/api/explain', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sentence, text_id: textId }),
    }),

  library: (kind?: string) =>
    request<{ days: LibraryDay[] }>(`/api/library${kind ? `?kind=${kind}` : ''}`),

  deleteText: (id: number) =>
    request<{ deleted: number }>(`/api/texts/${id}`, { method: 'DELETE' }),

  deleteActivity: (id: number) =>
    request<{ deleted: number }>(`/api/activities/${id}`, { method: 'DELETE' }),

  activitiesToday: () => request<{ activities: Activity[] }>('/api/activities/today'),

  activitySubmit: (id: number, answers: number[], seconds: number) =>
    request<{ id: number; score: number; total: number }>(
      `/api/activities/${id}/submit`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers, seconds }),
      },
    ),

  coachTip: () => request<{ tip: GrammarTip | null }>('/api/coach/tip'),

  writingPrompt: () =>
    request<{ prompt: string; focus: string; learning_words: string[] }>(
      '/api/writing/prompt',
    ),

  writingSteps: () => request<WritingTask>('/api/writing/steps'),

  writingCheck: (sentence: string, ask?: string) =>
    request<SentenceCheck>('/api/writing/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sentence, ask }),
    }),

  writingFinish: (sentences: WrittenSentence[], scenario: string, seconds: number) =>
    request<GuidedResult>('/api/writing/finish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sentences, scenario, seconds }),
    }),

  writingSubmit: (text: string, prompt: string, seconds: number) =>
    request<WritingResult>('/api/writing/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, prompt, seconds }),
    }),

  submitQuiz: (textId: number, answers: number[]) =>
    request<{ score: number; total: number }>(`/api/texts/${textId}/quiz`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answers }),
    }),

  narrate: (textId: number) =>
    request<{ path: string; marks: NarrationMark[]; cached: boolean }>(
      `/api/texts/${textId}/narrate`,
      { method: 'POST' },
    ),

  /* Conversación hablada (M19). `say` sube audio y devuelve los dos lados
     del turno; tarda ~5 s, así que la pantalla tiene que enseñar que está
     pensando o parece colgada. */
  conversationActive: () =>
    request<{ conversation: ActiveConversation | null }>('/api/conversation/active'),
  shadowList: () => request<{ sessions: ShadowSummary[] }>('/api/shadow'),
  shadowGet: (id: number) => request<ShadowSession>(`/api/shadow/${id}`),
  /* Devuelve la sesión ya lista, o el id del trabajo que la está preparando:
     bajar y transcribir tarda minutos y no cabe en una petición HTTP. */
  shadowCreate: (url: string) =>
    request<ShadowCreated>('/api/shadow', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    }),
  shadowMark: (lineId: number, done: boolean) =>
    request<ShadowSession>(`/api/shadow/line/${lineId}?done=${done}`, {
      method: 'POST',
    }),

  conversationWarm: () =>
    request<{ model: boolean; voice: boolean }>('/api/conversation/warm', {
      method: 'POST',
    }),
  conversationStart: (topic?: string) =>
    request<ConversationOpening>('/api/conversation/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic: topic || null }),
    }),
  conversationSay: (id: number, audio: Blob) => {
    const form = new FormData()
    form.append('audio', audio, 'turn.webm')
    return request<ConversationTurn>(`/api/conversation/${id}/say`, {
      method: 'POST',
      body: form,
    })
  },
  conversationFinish: (id: number) =>
    request<ConversationSummary>(`/api/conversation/${id}/finish`, { method: 'POST' }),

  speakingPrompt: () =>
    request<{ prompt: string; learning_words: string[] }>('/api/speaking/prompt'),

  speakingSubmit: (audio: Blob, prompt: string) => {
    const form = new FormData()
    form.append('audio', audio, 'recording.webm')
    form.append('prompt', prompt)
    return request<SpeakingResult>('/api/speaking/submit', { method: 'POST', body: form })
  },

  aiStatus: () => request<AIStatus>('/api/ai/status'),

  generateReading: (opts: { level: string; minutes: number; topic: string }) =>
    request<GenerateResult>('/api/generate/reading', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts),
    }),

  finishText: (id: number, seconds: number, wordsAdded: number) =>
    request<{ ok: boolean; reading_minutes_today: number }>(`/api/texts/${id}/finish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seconds, words_added: wordsAdded }),
    }),
}

/* Ask the coach for something slow and wait without holding the request open.
   The work happens in the server's single worker — one inference at a time —
   so `onTick` reports honestly whether we are waiting our turn or being
   written right now. */
export async function runJob(
  kind: JobKind,
  params: Record<string, unknown>,
  onTick?: (job: Job) => void,
  everyMs = 1500,
): Promise<Job> {
  let job = await api.enqueue(kind, params)
  onTick?.(job)
  while (job.status === 'queued' || job.status === 'running') {
    await new Promise((r) => setTimeout(r, everyMs))
    job = await api.job(job.id)
    onTick?.(job)
  }
  return job
}

/* ~A1 function words rendered plain in the reader — implicitly known;
   marking them would drown the signal. */
export const STOPWORDS = new Set(
  (
    'the a an and or but if then than that this these those there here of in on at by for ' +
    'with from to into onto out up down over under about as is am are was were be been being ' +
    'do does did done have has had having will would shall should can could may might must ' +
    'not no nor so such very too also just only even still yet again more most much many ' +
    'few little less least own same other another each every all any some both either neither ' +
    'i you he she it we they me him her us them my your his its our their mine yours hers ours ' +
    'theirs myself yourself himself herself itself ourselves themselves who whom whose which ' +
    'what when where why how because while during before after until since between among ' +
    'against through above below off once twice now soon never always often sometimes ' +
    "don't doesn't didn't won't wouldn't can't couldn't shouldn't isn't aren't wasn't weren't " +
    "it's that's there's let's i'm you're we're they're i've you've we've they've i'll you'll " +
    'he’s she’s'
  ).split(/\s+/),
)
