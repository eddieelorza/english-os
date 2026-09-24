# CLAUDE.md — Instrucciones para Claude Code

> Este archivo lo lee Claude Code automáticamente al iniciar una sesión en este proyecto. Si lo editas, las siguientes sesiones lo verán de inmediato.

## Qué es este proyecto

**English OS**: aplicación personal local-first para aprender inglés (A2/B1 → C1).
SRS propio con FSRS, lectura interactiva, práctica, writing, speaking, podcast y
stats — todo sobre `data/english.db`, corriendo en el Mac de Eddie.

> ### ⚠️ El pipeline legacy está apagado
>
> - **Anki: congelado** el 2026-08-21 ([ADR-011](docs/adr/ADR-011-anki-cutover.md)).
>   El mazo sigue instalado e intacto, pero nadie escribe ni lee de él.
>   `run_all.py session-end` se retira solo.
> - **Notion: apagado** el 2026-08-21 ([ADR-012](docs/adr/ADR-012-notion-off.md)).
>   Las páginas quedan como archivo legible, pero **cualquier escritura levanta
>   `NotionOff`**. El contenido (155 páginas, 479 KB) está rescatado en `texts.body`.
>
> Estado y marcha atrás: `scripts/cutover.py status` · `scripts/notion_off.py status`.
>
> **No propongas correr `run_all.py morning`, `session-end`, `sync-used` ni
> `reset`**: escriben en Notion y fallarán. Todo lo que hacían lo hace la app.

Lectura previa obligatoria:
- `README.md` — instalación y flujo
- `docs/adr/` — las decisiones, sobre todo ADR-006 (el pivote), ADR-009 a 012 y
  ADR-014 (carga adaptativa: presupuesto en cards, compuerta de nuevas, triage al volver)
- `DESIGN.md` — el mundo visual, antes de tocar UI

## Rol de Claude en el día a día

La app genera y corrige sola: al cerrar una sentada en Review encola la lectura,
las actividades y el consejo del día (`session.end` → `jobs.enqueue_daily`).

**Tu trabajo** cuando Eddie te invoque ya no es completar páginas de Notion, sino
trabajar sobre la app: leer de `data/english.db`, correr sus módulos, y sobre
todo **conversar y enseñar** — que es lo que ningún script hace.

## Diccionario de frases-comando

| Frase de Eddie (o similar) | Qué haces |
|---|---|
| **"qué tengo pendiente hoy"** | `curl localhost:8770/api/today` — cards vencidas, práctica, writing, lectura pendiente, racha y nivel con su razón. Resúmeselo. |
| **"dame la lectura del día"** | Mira si ya existe (`texts` con `kind='reading'` y la fecha de hoy). Si no, encólala: `POST /api/jobs {"kind":"reading"}`. **No la generes tú a mano en paralelo** — duplicarías el material del día. |
| **"hazme preguntas de comprensión"** | La lectura ya trae quiz. Si quiere más, pregúntale tú: 3-5 preguntas mezclando literal, inferencia y vocabulario en contexto; una de opinión. |
| **"revísame el writing"** / **"corrige"** | La app corrige sola desde Writing. Si te pide a ti: corriges SOLO lo que escribió él; ≤8 errores categorizados (`[ART]`, `[PREP]`, `[S-V]`, `[COLL]`, `[TENSE]`, `[REG]`, `[WORD]`); versión B2; 1 fortaleza + 1 cosa a practicar. Los errores van a la tabla `errors` de SQLite — **no a Notion**. |
| **"dame stats de la semana"** | `curl localhost:8770/api/stats`. Trae la tabla de evidencia, retención, y lo que cuesta el retraso. Respeta los "no data yet": no inventes números. |
| **"cómo voy"** | `/api/model` — el Personal English Model con su recomendación y la evidencia que la sostiene. |
| **"escribe el material de hoy"** / **"lectura|podcast|practice al momento"** | Lo escribes TÚ, sin API ni Ollama (ADR-016 D5). `curl localhost:8770/api/routine/brief/{reading|podcast|practice}`: si trae `skip`, no escribas nada — ya hay material sin usar. Si no, redacta siguiendo `system`/`prompt`/`schema` tal cual y mándalo a `POST /api/routine/submit/{kind}`. La app valida con sus reglas: 409 si el día ya lo tiene, 422 con el motivo. Sin servidor: `.venv/bin/python -c "from app import db,routine; ..."`. |
| **"pausa el curso"** | `POST /api/pause` con la razón. Congela la cola sin romper la racha. |

**Nunca** generes material duplicado: si el día ya tiene lectura o actividades,
no las vuelvas a pedir.

Eddie habla mezclando español/inglés. No te ofendas si es directo (no le gustan los rodeos). Responde en español por defecto; el inglés es para el contenido de aprendizaje.

## Convenciones técnicas

### Setup obligatorio en cada sesión
```python
# Load .env (priority over shell)
from pathlib import Path
import os
for line in Path('.env').read_text().splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, _, v = line.partition('=')
        os.environ[k.strip()] = v.strip().strip('"').strip("'")
```

O simplemente: `run_all.py` ya hace esto al importarse. Si vas a usar el cliente Notion, importa primero `run_all` o carga `.env` manualmente.

### Cliente Notion
**Usa siempre** `scripts/notion_client.NotionClient` y `scripts/notion_blocks.*` — nunca llames `requests` directo. El cliente trae retry/backoff para 429 y 5xx.

```python
import sys; sys.path.insert(0, 'scripts')
from notion_client import NotionClient
from notion_blocks import paragraph, heading, get_title, get_rich_text, block_plain_text

c = NotionClient()  # lee NOTION_TOKEN de env
page = c.find_first(os.environ['WRITING_DB_ID'], {"property":"Task","title":{"equals":"Writing Session – 2026-06-01"}})
children = c.get_block_children(page['id'])  # paginado automático
c.append_block_children(page['id'], [paragraph("hello")], after="<block_id>")
c.delete_block("<block_id>")
```

### ⚠️ Cut-over de Anki hecho el 2026-08-21 (ADR-011)

**Anki ya no cuenta.** La app (`data/english.db` + FSRS in-app) es la única
fuente del scheduling. El mazo sigue instalado e intacto, congelado como
archivo: nadie escribe en él ni lee de él.

Consecuencias para ti, Claude:

- `run_all.py session-end` **se retira solo** y no hace nada. No lo propongas
  como forma de procesar el día.
- `app/importers/anki.py` se detiene solo. Si alguna vez necesitas correrlo
  (no deberías), exige `force=True` y entiende que pisará `status` con datos
  viejos de Anki.
- El material del día lo dispara **cerrar una sentada en la app**
  (`session.end` → `jobs.enqueue_daily`), no el add-on.
- Estado y marcha atrás: `python3 scripts/cutover.py status | revert`.
- **Notion sigue siendo espejo** — este corte cierra Anki, no Notion.

Todo lo que sigue en esta sección describe el pipeline legacy tal como
funcionaba **antes** del corte. Se conserva porque `revert` lo devuelve.

### Automatización session-end (ADR-001/002, 2026-07-29) — legacy, retirado
El add-on de Anki lanzaba `run_all.py session-end` automáticamente al terminar cada
sesión de estudio: sync + writing + reading + `data/learner_profile.json` +
`scripts/daily_plan_update.py` (fila del día en **Daily Plan** `DAILY_PLAN_DB_ID`
+ callout `🎯 TODAY` al inicio de la página `ENGLISH_SYSTEM_PAGE_ID`). Control de disparo (ADR-001 rev. 2026-07-30): el add-on dispara tras **2 min sin
contestar cards** (o al cerrar Anki), no al volver al deck browser; `run_all`
exige `MIN_SESSION_REVIEWS` (default 10) para procesar el día, y el material se
pide a la nube **una sola vez al día** (`routine_fired_on` + `AI Session`=fecha).
`--force` salta las tres compuertas. Estado en `logs/.session_state.json`;
manual: `run_all.py session-end [--force]`. La fila Daily Plan tiene `Status` y `Results` que son de
Eddie/corrección — el script nunca los sobreescribe. Cuando corrijas un writing
("revísame"), además de `Corrected=true` actualiza `Results` de la fila Daily Plan
del día con un resumen breve (errores por categoría). OJO: en VOCAB, `Last
Reviewed` es tipo `last_edited_time` (drift); usa `Synced On` para "palabras de hoy".

Capa cognitiva (ADR-003): la routine cloud `trig_01HvnwuNc1PinNW1gGnLQ2AE`
("English Coach — Session Material", prompt en `docs/routine-prompt.md`) genera
historia + actividades + recomendación vía conector Notion, sin API key. Disparo:
`fire_routine()` en session-end (necesita `ROUTINE_ID` + `ROUTINE_FIRE_TOKEN` en
.env) o cron de respaldo 03:30 UTC. Idempotencia: propiedades `AI Session` /
`AI Status` en la fila Daily Plan — si `AI Status=Done`, la routine no regenera.
Si el material del día ya existe, no lo dupliques tú tampoco.

Fase 2 (ADR-004): la routine `trig_019tMdcUrsbByYZa9fT4obGc` ("Review & Errors",
cron 14:00 y 22:00 CDMX, o `run_all.py review`) corrige sola los writings con
`Ready for Review=true` y `Corrected=false`, y llena **Error Library**.
`scripts/error_metrics.py` agrega esos errores (ventana 14d) y de ahí sale el
`Target Errors` del Daily Plan y el foco del día — ya no hay lista hardcodeada.
Con <150 palabras producidas en la ventana, las métricas de precisión deben
mostrarse como "Sin datos suficientes"; nunca inventes un número.

### English Learning OS local-first (ADR-006, 2026-08-20)
El proyecto evoluciona a una app personal local-first (roadmap M0–M7 en
`docs/adr/ADR-006-english-os-local-first.md`; `docs/legacy/REDESIGN.md` y
`docs/legacy/BLOCKERS.md` quedaron superseded). **M0 implementado**: `data/english.db` (SQLite, gitignored) es la
fuente de verdad — 3,100+ words con estados NEW/LEARNING/FAMILIAR/MASTERED,
review_history (revlog de Anki), errors, sessions, texts. Código en `app/db.py` +
`app/importers/` (idempotentes); dual-write al final de `session-end` (paso no
fatal) o manual: `python3 run_all.py local-db`. Tests: `python3 -m unittest
discover tests`. Regla ADR-006: código nuevo LEE de SQLite; Notion solo recibe
escrituras espejo hasta apagarse módulo a módulo. M1 (próximo): FastAPI + React
+ TypeScript + Tailwind + Motion; al arrancar correr `uipro init --ai claude` y
usar la skill `/impeccable`. Reviews pre-junio 2026 (deck viejo, 3,016 filas de
revlog) no son vinculables a palabras — limitación documentada.

### Schema implícito de las DBs (NO está validado en código, no lo asumas si te falla)
- **VOCAB** (`VOCAB_DB_ID`): `Word` (title), `Source` (select), `Anki Note ID` (number), `Anki State` (select), `Ease`, `Lapses`, `Review Count` (number), `Last Reviewed`, `Synced On` (date), `Deck`, `Meaning (EN)`, `Meaning (ES)`, `Pronunciation` (rich_text), `Used Today` (checkbox), `Times Used` (number).
- **WRITING** (`WRITING_DB_ID`): `Task` (title), `Date`, `Corrected` (checkbox), `Tense Focus` (select).
- **READING** (`READING_DB_ID`): `Title` (title), `Date` (date).

### Reglas de seguridad
- **Nunca** modifiques una página sin verificar primero qué hay (lee `get_block_children` antes de borrar o reescribir).
- **Nunca** corras `run_all.py morning` ni `reset` ni `sync-used` sin que Eddie lo pida explícitamente — todos tienen side effects en Notion.
- **Nunca** asumas que ya rotó el token; si una llamada falla con 401, dile que regenere en notion.so/my-integrations.
- **Nunca** commits a git automáticos. Sí puedes proponer commits y mostrar el mensaje; él confirma.

### Lockfile
`run_all.py` usa `fcntl.flock` sobre `logs/.pipeline.lock`. Si lanzas el pipeline desde un script tuyo, igual respeta el lock (no lo bypasses).

## Convenciones pedagógicas (importantes)

Cuando generes contenido en inglés para Eddie:

- **Nivel objetivo**: B1→B2 con stretch a B2→C1. Historias en B1 (tiempos simples + perfecto), correcciones a B2 (introduce condicionales, modales, voz pasiva cuando aplique).
- **Vocabulario**: usa siempre las palabras del día como restricción dura, no como sugerencia. Permitido: formas derivadas (`forge` → `forged`, `prosper` → `prosperous`, `arise` → `arose`).
- **Longitud historia**: 330-370 palabras. No te pases.
- **Estilo**: realista, contemporáneo o histórico, no fantasía épica. Personajes con nombre. Conflicto + resolución.
- **Comprensión**: 3-5 preguntas, mezcla literal + inferencia + vocabulario en contexto. Una pregunta debe ser de opinión / aplicación.
- **Corrección de writing**: categoriza cada error como `[ART]`, `[PREP]`, `[S-V]`, `[COLL]` (colocación), `[TENSE]`, `[REG]` (registro), `[WORD]` (palabra mal elegida). Da la versión correcta + 1 línea de por qué. No marques más de 8 errores a la vez (sobrecarga); si hay más, escoge los 5 más educativos.
- **Feedback**: termina siempre con 1 fortaleza concreta + 1 cosa específica a practicar.

## Cómo verificar que todo sigue funcionando

Ver "Plan de pruebas" en `README.md`. Resumen rápido:
```bash
# Pre-flight: Notion + AnkiConnect + symlink
python3 -c "..."  # (script pre-check en mensaje anterior)

# Demo de generación de reading
python3 run_all.py morning  # crea páginas
# luego: "dame la lectura del día"

# Verificar lockfile
(python3 run_all.py morning &) ; sleep 0.1 ; python3 run_all.py morning
```

## Estado del rediseño pedagógico

Ver `docs/legacy/REDESIGN.md` para el plan completo. Estado al 2026-06-01:

- **Motor 1 (Input Engine)** — stub. Bloqueado por decisión de Whisper backend (ver `docs/legacy/BLOCKERS.md` → B-IN-1).
- **Motor 2 (Sentence Mining)** — stub.
- **Motor 3 (Output Engine — deck Errores)** — stub.
- **Motor 4 (Speaking Engine — shadowing)** — stub.
- **Motor 5 (Dashboard + Probe)** — stub.

**Desactualizado desde el cut-over (ADR-011).** La app es hoy el sistema de
producción: SRS propio con FSRS, lectura, práctica, writing, speaking, podcast
y stats, todo sobre `data/english.db`. Los scripts de Notion
(`writing_session_daily`, `reading_page_daily`, `sync_used_words`,
`reset_used_today`) siguen vivos como espejo; `anki_notion_sync` ya no aporta
nada porque Anki está congelado.
