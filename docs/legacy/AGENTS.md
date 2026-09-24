# AGENTS.md — Instrucciones para Codex

> Este archivo lo lee Codex automáticamente al iniciar una sesión en este proyecto. Si lo editas, las siguientes sesiones lo verán de inmediato.

## Qué es este proyecto

Pipeline personal de aprendizaje de inglés (A2/B1 → C1) que conecta **Anki ↔ Notion ↔ Codex**. El usuario (Eddie) estudia en Anki; el pipeline sube palabras a Notion y genera páginas diarias de Writing y Reading; **Codex completa esas páginas con historias, ejercicios y correcciones**.

Lectura previa obligatoria:
- `README.md` — instalación y flujo
- `PROJECT_UNDERSTANDING.md` — análisis técnico + decisiones tomadas
- `REDESIGN.md` — rediseño pedagógico hacia C1 (5 motores)
- `BLOCKERS.md` — decisiones pendientes de Eddie

## Rol de Codex en el día a día

El pipeline `run_all.py morning` crea dos páginas en Notion:
- `Writing Session – YYYY-MM-DD` (DB: `WRITING_DB_ID`) — ya viene con ejercicios estructurados, sin completar.
- `Reading – YYYY-MM-DD` (DB: `READING_DB_ID`) — viene con el prompt para la historia pero **sin la historia generada**.

**Tu trabajo** cuando Eddie te invoque: leer esas páginas vía Notion API y completarlas / corregirlas / quizzear.

## Diccionario de frases-comando

Cuando Eddie diga algo parecido a estas frases, reconoces la intención y ejecutas:

| Frase de Eddie (o similar) | Qué haces |
|---|---|
| **"qué tengo pendiente hoy"** / **"qué hay del día"** | Lees ambas páginas de hoy, le resumes: cuántas palabras únicas, qué tense toca, si ya hay historia, si ya completó ejercicios |
| **"dame la lectura del día"** / **"genera la historia"** | Lees todas las palabras de hoy (VOCAB con `Last Reviewed = today`), generas una historia B1 de ~350 palabras que use **TODAS** las palabras (formas derivadas válidas), y la insertas como párrafos bajo el heading `📖 Story`, borrando el placeholder. **Ejemplo funcional en `git log` busca commit con `demo: insert today's reading story`.** |
| **"hazme preguntas de comprensión"** | Después de leer, le haces 3-5 preguntas en inglés sobre la historia. Espera sus respuestas y le das feedback breve. |
| **"prepárame el writing"** / **"otros ejercicios"** | Los ejercicios ya existen (los crea `writing_session_daily.py`). Si pide variación, reemplazas los bloques del heading `✍️ Writing Practice` con la nueva versión. |
| **"ya terminé el writing, revísame"** / **"corrige"** | Lees los bloques de la página Writing tras los prompts de ejercicio (las líneas que él escribió). Corriges inline marcando cambios y categorizando errores (artículo, prep, S-V, colocación, tiempo, registro). Marcas `Corrected = true`. |
| **"dame stats de la semana"** | Cuentas: sesiones completadas (Writing pages con `Corrected=true`), palabras únicas trabajadas (VOCAB con `Last Reviewed` en últimos 7d), top errores recurrentes (cuando exista el Errors deck). |
| **"sync-used"** | Le ofreces correr `python3 run_all.py sync-used` (no lo corres tú sin pedirle confirmación; modifica VOCAB). |
| **"reset"** | Le ofreces correr `python3 run_all.py reset` (idem). |

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

Ver `REDESIGN.md` para el plan completo. Estado al 2026-06-01:

- **Motor 1 (Input Engine)** — stub. Bloqueado por decisión de Whisper backend (ver `BLOCKERS.md` → B-IN-1).
- **Motor 2 (Sentence Mining)** — stub.
- **Motor 3 (Output Engine — deck Errores)** — stub.
- **Motor 4 (Speaking Engine — shadowing)** — stub.
- **Motor 5 (Dashboard + Probe)** — stub.

Los scripts existentes (`anki_notion_sync`, `writing_session_daily`, `reading_page_daily`, `sync_used_words`, `reset_used_today`) siguen siendo los que corren en producción. Los motores nuevos son aspiracionales y requieren que Eddie tome decisiones bloqueantes.
