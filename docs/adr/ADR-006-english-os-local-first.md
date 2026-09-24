# ADR-006 — English Learning OS local-first

> Estado: **aceptado** (2026-08-20, decisiones de Eddie por opción múltiple).
> Enmienda al Product Vision §6 (no-goals #1 y #3). Supersede parcialmente
> REDESIGN.md y BLOCKERS.md (ver §6).

## Contexto

El sistema actual funciona (pipeline diario Anki→Notion + routines cloud), pero
el **system of record no es local**: el vocabulario vive en Notion, el historial
SRS vive en Anki, y localmente solo hay `data/learner_profile.json`. Eddie
decidió evolucionar hacia una app personal local-first ("English Learning OS")
que combine SRS, lectura interactiva estilo LingQ, tutor AI, speaking y
analytics — sin reconstruir desde cero y sin romper la rutina diaria.

## Decisiones

| # | Decisión | Alternativas descartadas |
|---|---|---|
| D1 | **SQLite** (`data/english.db`) es la fuente de verdad desde M0. SQL portable para poder migrar a Supabase (cloud o self-hosted) si aparece una necesidad concreta (p.ej. móvil). | Supabase desde el día 1 (infra sin necesidad actual); markdown como DB (no consultable). |
| D2 | **UI: app web local** (M1+): backend FastAPI + frontend **React + TypeScript + Tailwind + Motion**. Al iniciar M1 se corre `uipro init --ai claude` (skill UI/UX Pro Max) y se usa la skill `/impeccable` (init → shape) para el sistema de diseño — objetivo explícito: estética de lectura tipo Kindle/LingQ, nunca dashboard genérico. | Plugin Obsidian (TypeScript desde cero, UI limitada); TUI. |
| D3 | **Obsidian = cerebro legible**, adelantado a M1: el vault `English_System/` recibe el Personal English Model como markdown con wikilinks. Nunca es la base de datos. | Obsidian como storage primario. |
| D4 | **SRS: Anki hasta M4**, luego FSRS in-app (`py-fsrs`) con import del historial. AnkiConnect + snapshot ya existentes se conservan como adaptador. | FSRS inmediato (rompe la rutina); AnkiConnect permanente (nunca independiente). |
| D5 | **Notion = espejo hasta apagarlo**: el pipeline sigue escribiendo a Notion sin cambios; cada módulo de la app apaga su espejo cuando esté probado (strangler pattern). | Corte rápido (pierde el dashboard diario que hoy funciona). |
| D6 | La capa AI se desacopla en `AIProvider` (Anthropic API / Ollama) en M3; las routines cloud actuales siguen vivas como respaldo hasta entonces. | — |

## Enmienda al Product Vision (§6 no-goals)

- **No-goal #1** ("No es una app. Sin frontend propio") — **enmendado**: sí habrá
  una app local. Justificación por principios: **P1** (Reading interactivo y
  Speaking exigen una superficie de producción/interacción que Notion no puede
  dar), **P4** (analytics de evidencia requieren datos estructurados propios) y
  **P5** (una app local simple sustituye a un sistema de 3 servicios externos
  acoplados; el diseño sigue siendo lo más simple que enseñe).
- **No-goal #3** ("No reemplaza Anki ni Notion") — **enmendado**: los reemplaza
  *gradualmente y con evidencia* (Anki en M4+, Notion módulo a módulo).
- No-goals #2 (single-user), #4 (sin ML propio), #5 (sin gamificación ansiosa),
  #6 (sin fonética de precisión) y #7 (no automatiza la voluntad) **siguen vigentes**.

## Roadmap

M0 datos (este ADR) → M1 app skeleton + Vocabulary + ObsidianAdapter →
M2 Reading interactivo (texto pegado) → M3 AI layer + generador de lecturas →
M4 FSRS + Today → M5 Personal English Model formal → M6 Speaking
(faster-whisper) → M7 Analytics.

## Schema SQLite v1 (M0)

Archivo: `data/english.db` (gitignored; backup = copiar el archivo). Override
con `ENGLISH_DB_PATH`. DDL en `app/db.py` (fuente canónica); resumen:

- **words** — una fila por palabra/frase. Claves de negocio: `anki_note_id`
  (UNIQUE) y `notion_page_id` (UNIQUE). Campos: `word`, `normalized`, `kind`
  (`word|phrasal_verb|expression|sentence`), `status`
  (`NEW|LEARNING|FAMILIAR|MASTERED`), `cefr`, `meaning_en`, `meaning_es`,
  `pronunciation`, `example_en`, `example_es`, `source`, `deck`, `ease`,
  `interval_days`, `lapses`, `review_count`, `times_used`, `last_reviewed_on`.
- **review_history** — historial SRS real importado del `revlog` de Anki
  (idempotente por `anki_revlog_id` UNIQUE). `rating` 1-4, `interval_days`,
  `ease`, `took_ms`, `review_kind`. Base del import FSRS en M4.
- **errors** — espejo local de Error Library (upsert por `notion_page_id`).
- **sessions** — una fila por día (desde `learner_profile.json` y el pipeline):
  `cards_reviewed`, `introduced`, `again`, `again_rate`, `words_produced`,
  `errors_total`, más columnas reservadas `reading_minutes`/`speaking_minutes`.
- **texts** — writings y readings (metadatos ahora; cuerpo cuando la app los
  genere). Upsert por `notion_page_id`.
- **schema_meta** — versión de schema y marcas de import.

### Derivación de `status` (v1, determinista)

Desde el estado Anki de la card más avanzada de la nota:

- queue `new` → **NEW**
- queue `learning`/`relearn` → **LEARNING**
- queue `review`: `interval < 21d` → **LEARNING**; `21–89d` → **FAMILIAR**;
  `≥ 90d` con `lapses ≤ 1` → **MASTERED** (si no, FAMILIAR)

Es una heurística honesta con los datos disponibles; FSRS (M4) la refina con
retención real. Palabras sin card de Anki (origen Notion/manual) entran como
NEW salvo evidencia de uso (`times_used > 0` → LEARNING).

## Implementación M0

- `app/db.py` — conexión, DDL, upserts. SQL portable (sin features exclusivas
  de SQLite) para mantener abierta la puerta Supabase/Postgres.
- `app/importers/anki.py` — lee una **copia** de `collection.anki2` (nunca la
  original; Anki puede tenerla bloqueada), registra la colación `unicase`,
  importa las 2,402 notas AJ-Basic + revlog completo.
- `app/importers/notion.py` — VOCAB (merge por `anki_note_id`, conserva
  `times_used` y meanings curados) + Error Library.
- `app/importers/profile.py` — `learner_profile.json` → `sessions`.
- `scripts/local_db_sync.py` — corre los tres importers (idempotentes); se
  añade como paso **no fatal** al final de `session-end` (dual-write) y como
  modo `run_all.py local-db`.
- Tests en `tests/` (unittest, stdlib): schema, idempotencia, derivación de status.

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Romper el pipeline diario | El paso local-db es no fatal y va al final; nada existente cambia de orden. |
| Drift `Last Reviewed` (last_edited_time) en VOCAB | El import usa `Synced On` y el revlog de Anki, nunca `Last Reviewed`. |
| Doble fuente de verdad transitoria | Regla: desde M0, cualquier código nuevo LEE de SQLite; Notion solo recibe escrituras espejo. |
| Colección Anki bloqueada | Import sobre copia temporal; AnkiConnect no se usa para el histórico. |

## Documentos supersedidos

- `REDESIGN.md` — los "5 motores" quedan **superseded** por el roadmap M0–M7.
  Ideas absorbidas: M3 Output→Error Library (ya implementado, ADR-004), M4
  Speaking→M6, M5 Dashboard→M7. M1 Input Engine (yt-dlp) queda post-M7.
- `BLOCKERS.md` — B-IN-1 (Whisper) se resuelve en M6 con `faster-whisper`;
  B-OUT-1 (API key) se reabre en M3 (AIProvider); el resto queda superseded
  junto con REDESIGN.md.
- `docs/01_PRODUCT_VISION.md` §6 — enmendado según arriba (nota añadida en el
  propio documento).
