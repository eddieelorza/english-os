# BLOCKERS.md

> ⚠️ **SUPERSEDED (2026-08-20)** por [ADR-006](docs/adr/ADR-006-english-os-local-first.md):
> B-IN-1 (Whisper) se resuelve en M6 con `faster-whisper`; B-OUT-1 (API key) se
> reabre en M3 (AIProvider). El resto de bloqueadores pertenecía al plan de los
> 5 motores, superseded junto con REDESIGN.md. Se conserva como referencia histórica.

> Decisiones que necesito de ti para destrabar los motores pedagógicos.
> Cada bloqueador tiene un código (ej. **B-IN-1**) que está citado en REDESIGN.md y en los stubs de `scripts/motors/`.

Cuando vuelvas, en 10 minutos puedes resolver casi todos. El orden recomendado de abajo es el que **maximiza desbloqueo con mínimo esfuerzo**.

---

## 🚦 Orden recomendado de resolución

| Paso | Acción | Tiempo |
|---|---|---|
| 1 | Resolver **B-OUT-1, B-OUT-2, B-OUT-3, B-OUT-4** → desbloquea **M3 Output** (motor #1 por ROI) | ~10 min |
| 2 | Resolver **B-DA-2** → desbloquea **M5 Dashboard** | ~3 min |
| 3 | Resolver **B-IN-1, B-IN-2, B-IN-3** → desbloquea **M1 Input** (más pesado, mayor leverage) | ~15 min + instalar tooling |
| 4 | Resolver **B-SM-1, B-SM-2** → desbloquea **M2 Sentence Mining** | ~5 min |
| 5 | Resolver **B-SP-1, B-SP-2, B-SP-3, B-SP-4** → desbloquea **M4 Speaking** | ~20 min |

---

## M3 — Output Engine

### B-OUT-1 · Claude API key
**Qué necesito**: una API key de Anthropic para que el motor llame al modelo.
**Cómo**: ve a https://console.anthropic.com → API Keys → Create Key → cópiala.
**Dónde va**: en `.env`, agregar línea:
```
ANTHROPIC_API_KEY=sk-ant-…
```
**Costo estimado**: con Sonnet 4.6, cada corrección de un párrafo de free writing ≈ $0.005. 30 días/mes ≈ $0.15. Despreciable.

### B-OUT-2 · Nombre del deck Anki para errores
**Qué necesito**: nombre del deck destino. Recomendación: `English::Errors` (los `::` lo anidan bajo "English").
**Cómo**: créalo en Anki (Decks → Create Deck) o deja que el motor lo cree con `addNote` (Anki lo crea solo si no existe).
**Dónde va**: en `.env`:
```
ANKI_ERRORS_DECK=English::Errors
```
(Si dejas la línea fuera, el default es `English::Errors`.)

### B-OUT-3 · Notion DB "Error Categories"
**Qué necesito**: una nueva base de datos en Notion para contar las categorías de error.
**Cómo**: en Notion, crea una nueva DB con estas propiedades:

| Property | Type |
|---|---|
| Title | title |
| Count This Week | number |
| Count All Time | number |
| Last Occurred | date |
| Last Example | rich_text |

Comparte la DB con la integration `anki_eddie`. Copia el ID de la URL (`notion.so/<WORKSPACE>/<ID>?v=...`).
**Dónde va**: en `.env`:
```
ERRORS_DB_ID=…
```

### B-OUT-4 · Modelo Claude
**Recomendación**: `claude-sonnet-4-6` (balance precio/calidad para corrección gramatical y reformulación C1).
- Opus 4.7: ~3x mejor en sutilezas de registro, ~5x más caro. Considera para weekly review profundo.
- Haiku 4.5: muy barato, suficiente para detectar errores obvios; flojo para reformulación C1.

Default si no setteas nada: `claude-sonnet-4-6`. Si quieres cambiar:
```
CLAUDE_MODEL=claude-opus-4-7
```

---

## M5 — Dashboard

### B-DA-1 · Cadencia de ejecución
**Qué decidir**: cuándo correr `dashboard.py`.
- Opción A (recomendada): `launchd` los domingos 21:00.
- Opción B: manual al final del último día de estudio de la semana.
- Opción C: al final de cada `morning` (cada vez que cierras Anki) — corre seguido pero idempotente.

Si dudas, A. Yo te dejo el `.plist` listo cuando se implemente.

### B-DA-2 · Notion DB "Weekly Dashboards"
**Cómo**: crea DB con:

| Property | Type |
|---|---|
| Title | title |
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

Comparte con `anki_eddie`. En `.env`:
```
DASHBOARD_DB_ID=…
```

---

## M1 — Input Engine

### B-IN-1 · Backend de Whisper
**Qué decidir**: cómo transcribimos audio.

| Opción | Costo | Velocidad CPU | Calidad | Setup |
|---|---|---|---|---|
| `faster-whisper` (CTranslate2) | $0 | 3x más rápido que openai-whisper | Igual | `pip install faster-whisper` |
| `openai-whisper` | $0 | Lento sin GPU | Bueno | `pip install openai-whisper` + ffmpeg |
| OpenAI API (`whisper-1`) | $0.006/min | Muy rápido | Bueno | API key OpenAI |

**Recomendación**: `faster-whisper` con modelo `small.en` o `medium.en`. Gratis, suficientemente rápido en MacBook reciente.

Tu elección va a un constante en código + posiblemente nuevas deps en `requirements.txt`.

### B-IN-2 · Deck Anki para cards minadas
**Recomendación**: `English::Mined`. En `.env`:
```
ANKI_MINED_DECK=English::Mined
```

### B-IN-3 · Notion DB "Input Inbox"
**Cómo**: crear DB con:

| Property | Type |
|---|---|
| Title | title |
| URL | url |
| Source | select (YouTube / Podcast / Other) |
| Duration (s) | number |
| Status | select (pending / processing / done / failed) |
| Words Extracted | number |
| Processed At | date |
| Notes | rich_text |

Comparte con `anki_eddie`. En `.env`:
```
INPUT_DB_ID=…
```

### Otros bloqueadores M1 (resolución técnica, no decisión tuya)

- Necesitamos `yt-dlp` (`brew install yt-dlp` o `pip install yt-dlp`).
- Necesitamos `ffmpeg` (`brew install ffmpeg`).
- Si elegiste `faster-whisper`, necesitamos `pip install faster-whisper`. La primera corrida descarga el modelo (~150MB para `small.en`, ~500MB para `medium.en`).

---

## M2 — Sentence Mining

### B-SM-1 · Definición de "palabra conocida"
**Qué decidir**: cuándo consideras que una palabra ya no debe generar tarjeta nueva.

- Opción A (estricta, recomendada): `Anki State = review` Y `Review Count >= 3`. Garantiza que solo cards realmente aprendidas cuentan.
- Opción B (laxa): cualquier fila en Vocabulary Master, sin importar estado. Más rápido pero genera dups con cards que no recuerdas.

Recomendación: A.

### B-SM-2 · ¿Mantener Meaning (ES) en cards nuevas?
**Discusión**: la traducción ES corta es un crutch reconocido en SLA. Para llegar a C1 deberías estar pensando en inglés, no traduciendo.

- Opción A (recomendada B2→C1): solo mostrar EN definition + example sentence. ES se omite en cards nuevas.
- Opción B: mantener ES como hoy.
- Opción C: ES solo si EN definition no fue encontrada (fallback).

Recomendación: A si te sientes en B1+ sólido, sino C.

---

## M4 — Speaking Engine

### B-SP-1 · Recorder
**Mac**: `brew install sox` → comando `rec output.wav`.
Alternativa: AVFoundation via Python (más código pero sin deps externas).

Recomendación: sox. Es el menos código.

### B-SP-2 · DBs Notion
**Crear 2 DBs**:

**Shadowing Log**:
| Property | Type |
|---|---|
| Title | title |
| Source URL | url |
| Reps Today | number |
| Total Reps | number |
| Last Practiced | date |

**Speaking Log**:
| Property | Type |
|---|---|
| Title | title |
| Date | date |
| Topic | rich_text |
| Duration (s) | number |
| WPM | number |
| Errors / 100 words | number |
| Lexical Band | rich_text |
| Audio Path | rich_text |
| Transcript | rich_text |
| Feedback | rich_text |

Compartir con `anki_eddie`. En `.env`:
```
SHADOWING_DB_ID=…
SPEAKING_DB_ID=…
```

### B-SP-3 · Storage de audio
**Recomendación**: `audio/` en el repo, ya gitignored. Pros: junto al código, fácil de archivar. Contras: ocupa espacio del repo (no en git pero sí en tu Desktop).

Alternativa: `~/Documents/english_audio/`. Limpia el repo pero requiere config extra.

Default si no dices nada: `./audio/`.

### B-SP-4 · Frequency list
**Recomendación**: NGSL 5000 (https://www.newgeneralservicelist.com/). Curada para learners. Para C1 podemos sumar AWL (Academic Word List).

Alternativa: COCA top 5000. Más enfocado en inglés americano contemporáneo.

Default: NGSL.

---

## Resumen para tu vuelta

Cuando vuelvas, dime cuáles bloqueadores resolviste y cuál motor quieres que implemente primero. Mi recomendación es la misma que en REDESIGN.md:

1. **M3 Output** (1 día, mayor ROI) — necesito B-OUT-1..4
2. **M5 Dashboard** (medio día, alta visibilidad) — necesito B-DA-2
3. **M1 Input** (2 días, mayor leverage pedagógico) — necesito B-IN-1..3 + tooling

Mientras no haya respuesta, las opciones para el siguiente sprint son:

- Cerrar más deuda técnica pequeña (validar schema de Notion al arranque, rotación de logs, decidir watcher vs add-on de verdad)
- Escribir tests con `responses` para `notion_client.py`
- Documentar el flujo en un diagrama de secuencia más visual
