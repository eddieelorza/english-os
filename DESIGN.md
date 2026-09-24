# DESIGN.md — English OS visual system

> Recorded from the built world (M1, 2026-08-20). Direction: **The Assimil
> Workbook** — seed 62149694, chosen by Eddie on the decision page. Source of
> truth for tokens: `frontend/src/index.css` `@theme`.

## World

A mid-century European self-study language course, rendered as an app. The
screen is an open workbook page; the navigation is the course's cobalt cover
spine. The Spanish column exists but stays covered until asked (the Assimil
ritual, and Vision principle P1). It must never read as a SaaS dashboard.

## Tokens

| Token | Value | Role |
|---|---|---|
| `--color-paper` | `#FBFAF7` | ground (near-white paper — NOT cream) |
| `--color-ink` | `#16181C` | primary text |
| `--color-ink-soft` | `#4C4A44` | secondary text |
| `--color-ghost` | `#8F8C83` | tertiary/labels; ghosted NEW entries |
| `--color-rule` | `#E4E1D6` | hairline rules between entries |
| `--color-rule-strong` | `#C9C5B6` | search underline, NEW dashed mark |
| `--color-cobalt` | `#0A52C4` | structural: spine, active states, marks |
| `--color-cobalt-deep` | `#08409A` | cobalt text on paper |
| `--color-cobalt-wash` | `#EEF3FC` | hover wash |
| `--color-correction` | `#C6402D` | errors/"again" only — never decorative |

Light mode only, by scene: morning study at a desk on a Mac.

## Type

- `--font-book` **Source Serif 4 Variable** (fallback Charter/Georgia): the
  book voice — words, meanings, examples (italic), empty-state prose.
- `--font-ui` **Archivo Variable**: the apparatus — headings, labels, nav,
  numbers. Tracked uppercase at 10–13px for labels; extrabold tight for H1/H2.
- `font-feature-settings: 'tnum'` globally; counts use `.tnum`.

## Committed rules

1. **Cobalt is structural, never decorative** — the spine, the active tab
   rule, status marks, the ES cover chip. It owns whole regions (the rail).
2. **Status is margin ink that dries with mastery**: NEW = 1px dashed ghost
   rule + entry at 55% opacity ("unlit"); LEARNING = 2px solid cobalt;
   FAMILIAR = 2px cobalt at 35%; MASTERED = no mark. (The 2px marks are a
   deliberate world commitment — an exception to the generic side-stripe ban.)
3. **Exact counts, right-aligned** like hand-timed tracklists; never rounded,
   never progress rings.
4. **One motion law**: everything slides along its column axis,
   `{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }` (`SLIDE` in
   VocabularyPage.tsx) — row expansion vertical, ES uncover horizontal,
   tab rule via layoutId. No scattered hover effects.
5. **Spanish only on demand**: `lang="es"` content renders behind an
   "Uncover Spanish" dashed chip; uncovered ES is cobalt-deep serif.
6. **Rules, not cards**: content separates with 1px `--color-rule` lines and
   whitespace. No card grids, no shadows-as-structure, no rounded containers.
7. **Empty/loading states are drawn**: skeletons are faint ruled lines;
   empty pages say so in the book voice ("This page of the ledger is blank.").
8. **Browser surfaces themed**: selection cobalt/paper, caret cobalt, focus
   ring 2px cobalt, scrollbar rule-strong on paper.
9. **UI chrome in English**; correction red reserved for real errors.
10. Nav modules are **numbered lessons** (01–06 = the course roadmap M-order);
    unavailable lessons sit at 45% opacity, never hidden.

## Components in the wild

- **Spine** (`App.tsx`): cobalt rail, wordmark + "The self-study method"
  subtitle, lesson list; active lesson = paper bookmark tab (rounded-r-none,
  bleeds into the page on lg). Mobile: compact cobalt top bar.
- **Ledger entry** (`WordEntry.tsx`): margin mark, tabular index, serif word,
  ghost IPA, kind label (small caps cobalt), right SRS readout. Expands to:
  meaning/example (68ch max), ES cover, instrument readouts (dt ghost /
  dd ink), recent reviews, ruled status radiogroup.
- **Apparatus row** (`VocabularyPage.tsx`): underlined search line +
  uppercase status tabs with sliding cobalt rule.
- **Folio**: centered "page N of M" with PREV/NEXT.

## Reader (M2, built)

The same paper, book voice at reading measure (68ch, 17px/1.75). Every word
is a tappable button; **status ink as underlines** (`UNDERLINE` map in
ReaderPage.tsx):

- unknown (not in ledger): cobalt/60 dashed 1px — the invitation to tap
- NEW (in deck, unstudied): rule-strong dashed 1px (ghost)
- LEARNING: solid cobalt 2px · FAMILIAR: cobalt/35 2px · MASTERED: none
- ~A1 stopwords (`STOPWORDS` in api.ts) render plain — implicitly known.

Tap opens the **dictionary slip**: white card, rule-strong border, soft
offset shadow, word + IPA in book voice, meaning, example, Uncover-Spanish
chip, status radiogroup (known) or "Add to vocabulary" (unknown → LEARNING,
example sentence captured from the text). Finish renders a **colophon**:
ruled dl with time, length, known/learning/unknown counts, words added.
Pasted markdown emphasis (`**word**`) is stripped server-side.

## Review & Today (M4, built)

**Review** (`ReviewPage.tsx`): one centered card on the paper — bordered
`rule-strong` sheet, word in book voice at 4xl, IPA ghost. The answer opens
with the same slide law behind an "Uncover answer" action (the Assimil ritual
again — recall before reveal, Vision P1). Rating row: Again (correction
outline) / Hard / Good (neutral) / Easy (cobalt outline), with tabular keyboard
hints (space, 1–4). New entries announce themselves with a cobalt overline
label and arrive uncovered. Empty state in the book voice ("The deck is
clear."). **Today** (`TodayPage.tsx`): the day as a lesson spread — date as
the masthead, numbered rows (ruled, not cards) with a serif sentence each and
an uppercase cobalt CTA; streak as a right-aligned tabular fact, never a ring.

## Speaking (M6, built)

`SpeakingPage.tsx` — the same lesson-spread grammar: ruled sections, no
cards. "The coach asks" sets the question in book voice at 2xl with the
target words as cobalt facts beneath. Recording state is a pulsing
correction-red dot + tabular timer; the red is *live/attention*, honoring
its errors-only reservation (a recording light is the one other thing it
may mean). Corrections render as ✗ original (correction red) over
✓ corrected (cobalt semibold) with an uppercase category tag — the exact
visual grammar of the Error Library taxonomy. Strength/Practice close as a
ruled dl. The whole result slides in under the one motion law.

## Stats (M7, built)

`StatsPage.tsx` — evidence drawn in the workbook's own ink. A ruled fact
ledger (uppercase ghost labels over extrabold tabular numbers — never soft
tiles). Charts follow the dataviz method with the world as its design system:
**one cobalt series per chart** (small multiples instead of multi-series, so
no legends), thin marks with 2px-radius data ends, hairline `--color-rule`
grid, all text in ink/ghost tokens, per-mark hover tooltips, honest gaps
where data is missing (retention skips empty weeks), and the closing
accuracy line states "not enough data" rather than a number (Vision P4).
Palette validated with the dataviz script against `--color-paper`.

## Audio (M8, built)

The speaker mark is a **drawn SVG glyph** in cobalt (`Audio.tsx`), never an
emoji — it sits inline beside a word, grows to 22px on the Review flashcard,
and simply does not render when a word has no recording (callers never
branch). Deck audio (7,188 MP3s from the Essential English Words apkg) plays
in the ledger, the flashcard, and the dictionary slip.

**Shadowing rig** (`ReadingPlayer.tsx`): the narrated sentence lights up with
`--color-cobalt-wash` while every other sentence drops to 55% opacity — the
page reads as a moving spotlight, not a highlighter. Controls in one ruled
row: Play/Pause, Repeat sentence (the shadowing loop), Speed 0.8×/1×, and
**Now I read** — dropping the voice mid-flight is a first-class action, not a
stop button. Karaoke needs no aligner: TTS synthesizes sentence by sentence,
so offsets are exact. `SENTENCE_SPLIT` in the reader must mirror
`tts.split_sentences` on the server or the marks drift.

## Practice & Writing (M9, built)

Same ruled-list grammar as everything else — **no cards, no progress rings**.
`PracticePage.tsx`: each activity is a ruled section with an answered/score
counter; options are full-width bordered rows with the letter in `font-ui`
(the AI's own "a)" prefixes are stripped server-side so the letter is drawn
once). Selection = cobalt border + wash; on check, correct turns cobalt-solid,
your wrong pick turns correction-red, and the Spanish explanation slides in.
Listening questions carry the deck's `PlayButton` inline in the prompt.

The **grammar tip** closes the session as the one place a cobalt left-border
is allowed (`border-l-2` on a wash panel) — it is an aside, not a list item:
rule in book voice, then the ✗/✓ minimal pair, then the hook in italic.

`WritingPage.tsx`: the editor is plain ruled paper with a live tabular
`words · m:ss` line (measurement as by-product, Vision P2). The result opens
with a 3-column stat row, then **Tenses you used** — the analysis Eddie asked
for — as cobalt facts plus a ✓/✗ note on the day's focus, then corrections in
the shared ✗/✓ grammar, the B2 rewrite, and Strength/Practice.

Eight lessons no longer fit a narrow top bar: below `lg` the rail scrolls
horizontally (`overflow-x-auto`, `shrink-0` items) and drops the numbers.

## Sentence explanations & the archive (M10, built)

**The sentence mark** is a pilcrow (¶) in `font-ui` at the end of each
sentence, `hidden` until you hover that sentence — `hidden`, never
`opacity-0`: an invisible glyph still takes a slot and opens a ragged gap
after every sentence, which is exactly the kind of defect a reading surface
cannot afford. Clicking opens the explanation as a cobalt left-border aside
(same aside grammar as the grammar tip, never a modal over the text):
Means · Grammar · En español · Watch out, each a ruled `dt/dd` row.

**The archive**: shelves group by day under a hairline `border-b` heading
labelled *Today* / *Yesterday* / weekday + date — the file label of a course
archive, not a timestamp. Delete is a ghost word at the row's right edge that
appears on hover and turns correction-red reading "Sure?" for four seconds
before it commits — confirmation without a dialog. Practice and Writing carry
the same archive collapsed at the foot (`History.tsx`) so it never competes
with today's work.

## Podcast (M11, built)

`PodcastPage.tsx` — the studio, then the player. Episodes file themselves by
day like every other shelf. In the player, one ruled control row carries
Play/Pause, Repeat turn, Speed, **Mode** and the elapsed clock; mode is two
underlined words (Shadowing · Ear only), not a switch — it reads as a choice
in the apparatus, like the status tabs.

**Shadowing** renders the transcript as a two-column dialogue: the speaker
name in small caps (cobalt for A, ink-soft for B — the only place two
speakers are distinguished by color, and the pair carries a name label so
color is never the sole signal), the line in book voice. The spoken turn
lights `--color-cobalt-wash` while the rest drops to 55% — the reader's
spotlight, one level up (turns instead of sentences).

**Ear only** removes the transcript entirely and says so in the book voice.
It offers the target words as a listening cue, then the quiz. Emptiness is
the feature here: nothing to read is what trains the ear.

## The evidence table (M12, built)

Stats opens with **What your level is read from**: four ruled rows (recall,
comprehension, practice accuracy, free production), each carrying its
measurement, its sample size in tabular figures, and a verdict word —
`stretch` in cobalt, `consolidate` in correction red, `at level` / `not
enough` in ghost. Color never carries the verdict alone; the word does.

A source with no data says **"no data yet"** in ghost rather than showing a
zero, and the closing line states the principle in plain words: a day without
writing is not a blind day. The table is the honest answer to "how is my
knowledge being judged" — it shows the inputs, not just the output.

## Pause (M13, built)

Pausing is offered as a **ghost word at the foot of Today** ("Pause the
course") — available, never nagging. Asking why is one ruled input line, and
the reason is optional: friction here would defeat the point.

While paused the day becomes a **held page**: a cobalt left-border aside (the
same aside grammar as the grammar tip and the sentence explanation) that
states plainly what is *not* happening — nothing falling due, nothing new
introduced, **streak safe** — because the fear being answered is "I'm losing
ground". On resume it reports the arithmetic: how many cards were spread over
how many days, and whether Anki was reachable. No celebration, no guilt.

## Waiting (M14, built)

Generation is slow and now runs in a queue, so the waiting copy stops lying:
the button dims into **"The coach is writing…"** only while the job is really
running. Before that it says it is queued, and behind other work it says how
many jobs are ahead and *why* — "one at a time keeps the laptop cool". The
reason is stated once, in the place where the cost is felt, rather than hidden
in a settings screen.

No spinner and no progress bar: the system cannot honestly estimate a local
model's remaining time, and a bar that fills at an invented rate is a lie the
reader learns to distrust. A ghost italic line, in the same voice as the rest
of the workbook, carries the wait instead.

## The drill (M15, built)

Practice was a worksheet: twelve blanks in one column, one "Check answers"
button, all the explanations arriving at once at the end — the moment they are
least likely to be read. It is now a **session**.

One question fills the frame. Answering marks it *immediately* — the chosen
option turns correction red or the right one turns cobalt — and the *why*
opens beneath in a bordered aside, the same aside grammar as the grammar tip
and the sentence explanation. The explanation lands in the one second the
reader actually cares about it.

Progress is **one thin 3px segment per question**, filling cobalt for right
and correction red for wrong as you go. It is a spine, not a gauge: no
rounded gradient bar, no percentage. You can see at a glance both how far in
you are and how it is going, which a plain counter cannot show.

Sets chain into one run — "Set 2 of 3" — so the day's practice feels like a
single sitting rather than three separate forms, and each set saves the moment
its last question is answered, not at the end of the whole session.

The session closes on a **result card**: the score in the same oversized
tabular figures the Stats hero uses, the time taken, and "Worth another look"
— the missed questions with their right answer and reason, capped at four so
the card stays readable. A clean run gets one plain line, not a celebration.
No mascots, no confetti, no streak fireworks: the reward for finishing is
knowing what you got wrong.

Answering runs on the keyboard — **A/B/C or 1/2/3**, then **Enter** — with the
available key named in ghost type under the card. The Continue button is
deliberately *not* autofocused: a focused button turns Enter into a native
click that races the key handler and silently skips a question.

## The sitting (M16, built)

Review used to open straight onto a card with a badge reading how many were
due. Past a couple of hundred that badge is not information, it is a
reproach — the exact feeling the pause exists to prevent.

Now the deck opens on a **plan**. One line asks *how long do you have* (10 /
20 / 30 min, chosen the same way the reader picks a level), and the breakdown
sits under a rule before you commit: **"6 new · 24 reviews ≈ 20 min"**. If the
deck cannot fill the ask it says so in ghost italic — "only 5 reviews due" —
rather than quietly planning less. A ghost link swaps to exact numbers for the
days you want to say "6 and 25" and mean it.

The estimate names its own uncertainty: with fewer than 30 in-app cards
measured it prints **"pace not measured yet (22/30) — estimating 10s per
card"**. A number with no sample behind it should look like an estimate.

Once the sitting runs, the header counts **"12 of 29 this sitting"** and
nothing else. The backlog total is deliberately absent from the drill; it
reappears once, softly, on the closing card — "24 still due today, they are
not going anywhere" — where it is information rather than a weight.

Cards are **front-first, new words included**: word, pronunciation, audio,
then *Uncover answer*. A card handed over pre-opened is a poster, not a test.
A word rated *Again* returns inside the same sitting; a word you got right
moves on, so the sitting can actually end.

The sitting closes on the same result-card grammar as Practice: the count in
oversized tabular figures, the split of new versus reviewed, and two ways out.

Closing is also when the backlog gets tidied, so the card says what happened
to it in plain words — *"165 cards were spread over the next 14 days. You will
see them a little later than the schedule wanted — that is the price of not
meeting a wall."* The cost is named, not buried: this system trades a little
retention for never facing a pile, and the reader should know which trade they
are in. When even the spread cannot fit, a second line in correction red says
so and names the two real fixes (sit longer, or pause new words).

The one warning that lives in the planning screen is about **new words**,
because that is the dial that decides tomorrow's queue: *"2 new words a day
settles at about 13 reviews a day, more than the 3 your sitting holds — your
words have taken 6.3 reviews each so far."* It quotes the reader's own measured
number, and says "estimated" when there is not enough history to measure.

## The bill (M16d, built)

The sitting promises never to show a pile; the price of that promise is that
reviews arrive late. Stats now shows the price, in the same ruled-row grammar
as the evidence table — **"What answering late costs you"**: recall on time,
1–3 days late, 4+ days late, each with its sample.

Three numbers do not want a bar chart. Ruled rows put the value, the sample
and the band on one line and read faster than three bars ever would; the
dataviz method's first question is which form fits, and here the answer is
*not a chart*. A band under twenty reviews prints **"not enough to say"**
rather than a percentage — a 100% over three cards is not a measurement.

The opening line names the *cause* alongside the effect: either "162 cards
were rescheduled over 4 days in the last 30", or, when nothing was spread,
"any lateness here is simply days you did not study". Without that, a reader
cannot tell a system-imposed delay from their own week off, and the number
would quietly accuse them of the wrong thing.

Beneath it, one line chart — **days late per review, weekly** — with real gaps
where there were no in-app reviews. It uses the line, not columns, precisely
because columns render a missing week as a zero, and a zero here would read as
perfect punctuality.

## The four intervals (M17, built)

Each rating button now carries the interval it buys, set **above** the button
in ghost tabular figures — the way Anki does it, and for the same reason: the
number is a property of the *choice*, not a caption on the result. It answers
"when does this come back if I press this", never "how long have I been
studying this".

    10m        1d         1d         2d
   AGAIN      HARD       GOOD       EASY

The numbers are exact, not estimates, because the scheduler's fuzz is off. If
fuzz is ever switched on, the payload's `exact: false` is the signal to soften
the label — a button that promises 9 days and delivers 7 is worse than a
button with no number at all. Two ratings sometimes show the *same* interval
(a card just recovered from a lapse can only earn one day, whichever you
press); that is the truth, and the truth is what goes on the button.

Below the button, one word — **graduates** — appears on the rating that would
move the card out of the learning minutes for good. It is the only transition
in the lifecycle worth announcing before it happens.

The header names the three groups rather than totalling them: **"3 new · 2
learning · 18 due"**. A single "23 left" would hide that a learning card comes
back inside this sitting while a review vanishes for days.

## Writing, one sentence at a time (M20, built)

Four months of the free-writing page produced **three** sessions. "Four to six
sentences" sounds small, but it is still an empty box, and an empty box is the
wall. The one time the writing flowed it was a letter to a person — *"Hi
Arnold, I only writing you because…"*, 77 words — not an exercise.

So the page now opens on a **message from someone**, set in the cobalt aside
that already carries asides everywhere else. A name, two sentences, a question
worth answering. The Spanish line underneath sets the scene; the message
itself is English, because that is what he is replying to.

Then one sentence at a time, with the Practice drill's grammar: a segment per
sentence filling cobalt or correction red, the ask in Spanish above, and the
input **pre-filled with the first few English words**. That is the whole
trick — he is never starting a sentence, only continuing one. A placeholder
would not do it; placeholders vanish when you type and leave you at zero.

The correction lands in about four seconds, in the same bordered aside as
every other explanation: *Right as it is* or *Almost*, the repaired sentence
in cobalt, the reason in Spanish. Below, the reply grows paragraph by
paragraph under **"Your reply so far"** — the thing being built, visible while
you build it.

The close reuses the result-card shape: the word count in oversized tabular
figures, the assembled reply, one strength and one thing to practise. The
stored record keeps **what he wrote**, errors and all; the repaired version
lives beside it. Storing the corrected text would quietly erase his mistakes
from his own history.

## Words that are not moving (M22, built)

Eleven words — six percent of the deck — were eating sixteen percent of every
review and going nowhere: `rear` at twenty-two reviews and a one-day interval.
Nothing in the app named them. They simply came back, and the deck felt like
it was not working.

They now get a numbered row of their own on Today, in the same ruled grammar
as the rest of the day, with the words themselves in correction red. Naming
them is half the fix: an invisible problem reads as *the system is broken*
rather than *these eleven words are hard*.

The row says what the app is doing about it, because the answer is not more
cards: **they now lead the words every generator draws from**, so the reading,
the activities and the podcast are built with them. Repetition of a failing
card was the thing that already did not work — meeting the word inside a story
is a different encounter, not a louder one.

Two restraints matter. They are **not suspended** the way Anki does it: hiding
a word you want to learn fixes the metric, not the problem. And they take at
most **half** the slots in any generated material — a text made only of hard
words has no context left to hold on to, and comprehension needs mostly-known
ground with a little new in it.

## The shared apparatus (M23, built)

Ten lessons built one at a time had each drawn its own furniture: 65 button
class-strings (six different solid primaries), four page measures, grey block
skeletons against rule 7, and `SLIDE` living inside `VocabularyPage`. The
apparatus now lives in `frontend/src/ui/` and the pages import it; a page
never imports from another page.

| Piece | File | What it settles |
|---|---|---|
| `Page` | `ui/Page.tsx` | Three measures with names: `study` (2xl — Review, Practice, Writing, Speaking, Shadowing, Podcast, Reader), `evidence` (3xl — Today, Stats), `ledger` (4xl — Vocabulary, Reading). The outer margin reads the same on every lesson. |
| `PageHeader` | `ui/Page.tsx` | The masthead: optional overline, H2 (4xl extrabold, or 3xl serif with `serif` when the title is a text's own), optional subtitle, and the right-aligned tabular `meta` — counts, never a second heading. |
| `Section` | `ui/Page.tsx` | Rules, not cards (rule 6): `border-t` hairline, `mt-8 pt-6`, optional uppercase label. |
| `Button` / `ButtonLink` | `ui/Button.tsx` | One family: `primary` (cobalt fill), `secondary` (ruled), `danger` (correction outline, reserved), `text` (a word in the margin, tone `ghost` / `cobalt` / `correction`). Sizes `sm` and `md`. A destination renders as `ButtonLink`, so it keeps its URL. |
| `Choice` | `ui/Choice.tsx` | The answer row of the drill and the reading quiz: `idle` / `chosen` / `correct` / `wrong` / `muted`, with the letter drawn once. Multiple choice is the interaction this product leans on. |
| `RuledSkeleton` | `ui/States.tsx` | Rule 7 made real: loading is faint ruled lines at ragged widths, never grey blocks. |
| `Waiting` | `ui/States.tsx` | The local model takes 15–80 s. Ghost italic in the book voice, an optional queue note, inside `role="status" aria-live="polite"` — a silent screen reads as a hung one. |
| `ErrorLine` | `ui/States.tsx` | Correction-red italic in `role="alert"`, with an optional **Try again**. A failure with no way out is where a session ends. |
| `Empty` | `ui/States.tsx` | The blank page still speaks ("This page of the ledger is blank."). |
| `SLIDE`, `slide()` | `ui/motion.ts` | The one motion law (rule 4) and two amplitudes (`NEAR` 8, `FAR` 16) instead of nine ad-hoc distances. `main.tsx` wraps the app in `MotionConfig reducedMotion="user"`, so the slides become cuts when the system asks. |
| `fmt` | `ui/format.ts` | Exact counts (rule 3). It used to live in `VocabularyPage` and fourteen files imported it from there. |

What stays hand-drawn, because it is world and not apparatus: the rating row
of the four intervals, the tappable words and the ¶ of the reader, the
"Uncover Spanish" dashed chip, the status radios of the ledger, the player
control rows (their words are underlined choices, not buttons), the row that
is clickable in its entirety, and the hover "DELETE".

## Extending

Inherit this world; no new identity exercises. Any new module claims its
numbered lesson in the spine. Reuse the reader's status-ink grammar wherever
words appear in running text, and the single-series chart grammar wherever
numbers get drawn.
