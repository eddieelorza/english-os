# PROJECT_UNDERSTANDING.md

> Análisis técnico del repositorio **English_Automation_v2** desde la perspectiva de un Senior Staff Engineer.
> Fecha de análisis: 2026-05-30. Estado: lectura completa de código, configuración y logs reales. No se ha modificado ningún archivo.

---

## 1. Resumen ejecutivo

**English_Automation_v2** es un pipeline personal de aprendizaje de inglés que orquesta tres sistemas externos:

1. **Anki** (con el plugin AnkiConnect HTTP en `localhost:8765`) — fuente de palabras estudiadas.
2. **Notion** (API v2022-06-28) — destino donde viven tres bases de datos: *Vocabulary Master*, *Writing Practice* y *Reading Hub*.
3. **Claude / Notion AI** — agente humano-en-el-loop que genera historias, ejercicios y corrige.

El usuario estudia en Anki → al cerrar Anki o volver al deck browser, un add-on dispara `run_all.py morning` → este orquesta cuatro scripts secuenciales que (a) limpian el estado del día anterior, (b) suben las palabras estudiadas hoy a Notion, y (c) generan dos páginas diarias (Writing y Reading) listas para que el usuario las complete. Después, el usuario corre manualmente `sync-used` para reflejar qué palabras usó realmente en sus ejercicios.

Es un proyecto **single-user, single-machine, sin tests, sin CI, sin tipos**. La complejidad real está en la integración con dos APIs externas y en el contrato implícito con la estructura de las bases de Notion del usuario.

---

## 2. Estructura del proyecto

```
English_Automation_v2/
├── run_all.py                       ← orquestador (entry point)
├── README.md
├── .env.example                     ← NOTION_TOKEN + 4 DB IDs
├── anki_watcher.sh                  ← alternativa al add-on: poll de pgrep cada 10s
├── anki_addon/__init__.py           ← add-on Anki: hooks → dispara run_all.py morning
├── scripts/
│   ├── reset_used_today.py          ← (1) limpia checkbox "Used Today" en VOCAB
│   ├── anki_notion_sync.py          ← (2) AnkiConnect → upsert palabras a VOCAB
│   ├── writing_session_daily.py     ← (3) crea página "Writing Session – YYYY-MM-DD"
│   ├── reading_page_daily.py        ← (4) crea página "Reading – YYYY-MM-DD"
│   └── sync_used_words.py           ← (post-ejercicio) marca Used Today + Times Used
├── logs/                            ← un .log por día + watcher logs
└── {anki_addon,scripts}/            ← ⚠️ directorio basura: brace expansion fallida
```

### Dependencias

- **Externas en runtime**: `requests` (única dependencia pip explícita), `aqt`/`gui_hooks` (provistas por Anki, solo para el add-on).
- **Externas vía red**:
  - `http://localhost:8765` (AnkiConnect, requiere Anki abierto)
  - `https://api.notion.com/v1`
  - `https://api.dictionaryapi.dev` (definiciones EN + fonética)
  - `https://api.mymemory.translated.net` (traducción EN→ES, gratuita, sin auth)
- **Sin** `requirements.txt`, `pyproject.toml`, ni lockfile. Sin versión de Python fijada.

---

## 3. Componentes principales y responsabilidades

| Módulo | Responsabilidad única | Lectura | Escritura |
|---|---|---|---|
| `run_all.py` | Orquestación secuencial + logging a `logs/YYYY-MM-DD.log`. Tres modos: `morning`, `sync-used`, `reset`. Aborta en el primer fallo. | `argv[1]` | `logs/` |
| `anki_addon/__init__.py` | Engancha 3 hooks de Anki (`reviewer_did_answer_card`, `deck_browser_did_render`, `profile_will_close`). Si hubo reviews, lanza `run_all.py morning` con `subprocess.Popen` (fire-and-forget). Carga `.env` con un parser propio. | `.env` | tooltip Anki, proceso hijo |
| `anki_watcher.sh` | Alternativa "fuera de Anki": busy-loop `pgrep -x Anki` cada 10s, dispara pipeline al cierre. Notificación nativa de macOS con `osascript`. | proceso `Anki` | `logs/watcher.log` |
| `scripts/reset_used_today.py` | Recorre páginas de VOCAB con `Used Today = true` y las pone en `false`. Paginado. **1 update por página** (sin batch). | VOCAB | VOCAB |
| `scripts/anki_notion_sync.py` | Para cada nota de Anki estudiada hoy (`rated:1`), calcula stats agregadas (max reps/lapses/ease/queue), busca existing por `Anki Note ID`, enriquece con dictionaryapi + MyMemory si los meanings están vacíos, y upserta en VOCAB. Hace skip si ya se sincronizó hoy. `time.sleep(0.2)` entre palabras. | Anki, dictionaryapi, MyMemory, VOCAB | VOCAB |
| `scripts/writing_session_daily.py` | Lee palabras de VOCAB con `Last Reviewed = hoy`, construye bloques Notion (tabla, todo-list, párrafo de ejercicios estructurados). Rota *Tense Focus* por día de semana. Idempotente: si la página de hoy existe, **anexa** solo las palabras nuevas vía `extract_words_from_todos`. | VOCAB, WRITING | WRITING |
| `scripts/reading_page_daily.py` | Mismo patrón: una página "Reading – YYYY-MM-DD". Crea bloques con prompt B1 (350 palabras) pensado para Notion AI. Idempotente vía bullets `•`. | VOCAB, READING | READING |
| `scripts/sync_used_words.py` | Lee la página Writing de hoy → todos los to-do `checked: true` → por cada palabra busca en VOCAB y marca `Used Today = true`, incrementa `Times Used`. | WRITING, VOCAB | VOCAB |

---

## 4. Flujo end-to-end

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Usuario abre Anki y estudia                              │
│    → on_card_did_answer setea flag _had_reviews = True      │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│ 2. Vuelve al deck browser  ó  cierra Anki                   │
│    → on_deck_browser_did_render / on_profile_will_close     │
│    → si _had_reviews: subprocess.Popen(run_all.py morning)  │
│      fire-and-forget, logs/stdout descartados               │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│ 3. run_all.py morning  (secuencial, abort-on-error)         │
│    a. reset_used_today.py   → limpia VOCAB.Used Today       │
│    b. anki_notion_sync.py   → AnkiConnect findNotes rated:1 │
│                              → upsert por Anki Note ID      │
│                              → enriquece EN/ES si vacíos    │
│    c. writing_session_daily → crea/anexa Writing del día    │
│    d. reading_page_daily    → crea/anexa Reading del día    │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│ 4. Usuario completa ejercicios en Notion                    │
│    (Claude/Notion AI ayuda con story y corrección)          │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│ 5. Usuario corre manualmente: python3 run_all.py sync-used  │
│    → marca Used Today + Times Used += 1 en VOCAB            │
└─────────────────────────────────────────────────────────────┘
```

### Contratos implícitos con Notion (no validados en código)

- **VOCAB DB** debe tener: `Word` (title), `Source` (select), `Anki Note ID` (number), `Anki State` (select), `Ease` (number), `Lapses` (number), `Review Count` (number), `Last Reviewed` (date), `Synced On` (date), `Deck` (rich_text), `Meaning (EN)` (rich_text), `Meaning (ES)` (rich_text), `Pronunciation` (rich_text), `Used Today` (checkbox), `Times Used` (number).
- **WRITING DB**: `Task` (title), `Date` (date), `Corrected` (checkbox), `Tense Focus` (select).
- **READING DB**: `Title` (title), `Date` (date).
- Cualquier cambio de nombre de propiedad rompe el script silenciosamente o con 400 de la API.

---

## 5. Patrones de diseño y convenciones

**Patrones presentes:**
- **Idempotencia por título + anexo incremental** (writing/reading): si la página del día existe, no la recrea — extrae los to-dos / bullets existentes y solo añade lo nuevo.
- **Upsert por clave de negocio** (anki_notion_sync): query por `Anki Note ID`, update o create.
- **Helpers locales por archivo** (`rt()`, `title()`, `heading()`, `paragraph_blocks()`) — duplicados entre `writing_session_daily.py` y `reading_page_daily.py`.
- **Configuración por constantes "ajusta si tu Notion se llama distinto"** al inicio de cada script.

**Convenciones observadas:**
- Logs informales con emojis (`✅ Updated`, `🆕 Created`, `📚 Palabras hoy`).
- Mezcla español/inglés en strings, comentarios y nombres.
- `requests.Session()` por script (no compartida) — está bien para un proceso de corta vida.
- Timeouts presentes en la mayoría de POSTs a Notion, **ausentes** en algunos GETs (p.ej. `sync_used_words.py` el GET de children y POSTs no tienen `timeout=`).

---

## 6. Riesgos técnicos identificados (orden de severidad)

### 🔴 Alto

1. **Race condition real al disparar el pipeline en paralelo.**
   El add-on engancha *dos* hooks (`deck_browser_did_render` y `profile_will_close`) que pueden disparar muy seguido. En `logs/2026-05-30.log` líneas 100-121 se ven **dos ejecuciones interleaved** con salidas mezcladas. No hay lockfile ni guard. Sobre Notion esto puede crear páginas duplicadas o anexos duplicados (la query `find_reading_page_for_today` no es atómica respecto al create).

2. **Ruta del add-on apunta a un directorio que probablemente no existe.**
   `anki_addon/__init__.py:20` hardcodea `~/Desktop/English_Automation/run_all.py` pero el proyecto vive en `English_Automation_v2`. Si el usuario instaló el add-on tal cual, *nunca* corre. Esto explicaría por qué los logs de hoy son todos invocaciones manuales o por watcher.

3. **`run_all.py` corre `morning` cada vez** que el usuario termina una sesión de Anki, lo que incluye `reset_used_today.py` como primer paso. Si el usuario estudió por la mañana, completó sus ejercicios (Used Today marcado), y vuelve a estudiar por la tarde, el segundo run del día **borra el progreso de Used Today**. El "reset" asume "una sesión de estudio por día" — semántica frágil.

4. **`anki_notion_sync.py` aborta toda la sincronización si una sola palabra falla** (excepción HTTP sin try/except en el loop). Una palabra con caracteres raros en el dictionary o un 429 transitorio de MyMemory tumba la corrida.

5. **Notion paginación en `sync_used_words.py:51` y `find_vocab_page` no usa paginación**: solo lee la primera página de children (100 bloques) y solo la primera coincidencia de palabra. Una sesión Writing con muchos bloques anexados puede dejar checkboxes sin sincronizar.

### 🟠 Medio

6. **MyMemory rate limit**: la API gratuita corta a ~1000 requests/día por IP sin auth. Una sesión grande de Anki (50+ palabras nuevas) puede silenciosamente devolver basura como "MYMEMORY WARNING".

7. **`dictionaryapi.dev` puede devolver definiciones más largas que `60 char` ES o cortar en mal lugar**; `clean_spanish_translation` corta a `60` y puede dejar texto sin sentido.

8. **El add-on carga `.env` con un parser custom** que no maneja valores con `=` dentro, comillas escapadas, ni multilínea. Para este proyecto basta, pero es fuente de bugs sutiles si alguna vez se mueve un valor.

9. **`anki_watcher.sh` y el add-on son redundantes**: si ambos están activos, se dispara dos veces.

10. **Sin retries ni backoff**: cualquier 429/500 transitorio de Notion mata el script.

11. **Logs crecen sin rotación**. Hoy es trivial (KB), pero no hay limpieza.

12. **El directorio basura `{anki_addon,scripts}/`** existe vacío en la raíz — evidencia de un `mkdir` con brace expansion mal hecho. Inocuo pero feo.

### 🟡 Bajo

13. **Sin `requirements.txt` / `pyproject.toml`**. Reproducibilidad cero.
14. **Sin tests** — ni unitarios ni de contrato contra Notion.
15. **Duplicación de helpers** (`rt`, `heading`, `paragraph`) entre 3 archivos.
16. **`time.sleep(0.2)`** entre palabras hace la sync O(n) lenta; ya hay evidencia: el run de las 19:00:38 tardó 95s para AnkiConnect sync.
17. **Hardcoded `TZ_OFFSET = "-06:00"`** en `writing_session_daily.py:34` — funciona para CDMX, no si viajas.
18. **No hay `.gitignore`** visible — el repo dice "no es git repo". Si se sube tal cual, `.env` se filtra.

---

## 7. Mejoras sugeridas (priorizadas)

| Prioridad | Mejora | Esfuerzo | Valor |
|---|---|---|---|
| P0 | Lockfile (`logs/.pipeline.lock` con `fcntl.flock`) en `run_all.py` para impedir runs paralelos | Bajo | Alto |
| P0 | Corregir ruta hardcoded en `anki_addon/__init__.py:20` (`English_Automation` → `English_Automation_v2`) y documentar que debe ser configurable o leerse de `__file__` | Trivial | Alto |
| P0 | `reset_used_today.py` debería correr **solo una vez al día** (chequear marca en `logs/.reset-YYYY-MM-DD`), no en cada `morning` | Bajo | Alto |
| P1 | Envolver el loop principal de `anki_notion_sync.py` en try/except por palabra, con log de fallidas | Bajo | Alto |
| P1 | Paginar `sync_used_words.get_checked_words` (loop de `has_more`) | Bajo | Medio |
| P1 | Añadir retry con backoff exponencial para Notion (429/5xx) — `tenacity` o un wrapper custom | Bajo | Alto |
| P1 | Decidir add-on **o** watcher, eliminar el otro | Trivial | Medio |
| P2 | `requirements.txt` con `requests==X.Y.Z` + `.python-version` | Trivial | Medio |
| P2 | Extraer `notion_client.py` compartido (helpers `rt/title/heading/paragraph/divider`) | Medio | Medio |
| P2 | Validar nombres de propiedades al inicio (un GET a la DB schema) y fallar rápido con mensaje claro | Medio | Alto |
| P2 | TZ desde env (`TZ_OFFSET=os.environ.get(...)`) o usar `zoneinfo` | Bajo | Bajo |
| P3 | Tests de contrato: mockear AnkiConnect y Notion con `responses` para los happy paths | Alto | Medio |
| P3 | Borrar `{anki_addon,scripts}/` | Trivial | Cosmético |
| P3 | Rotación de logs (`RotatingFileHandler`) | Trivial | Bajo |

---

## 8. Hallazgos de verificación (post-Q&A)

Al verificar la instalación real del add-on en `~/Library/Application Support/Anki2/addons21/english_automation/__init__.py` aparecieron dos cosas críticas que no estaban en el repo:

1. **🔴 Token Notion + 4 DB IDs hardcoded en el add-on instalado** (líneas 14-18). El token `ntn_…` está en plano dentro de la carpeta de plugins de Anki. Cualquiera con acceso a esa máquina o a un backup de Anki lo tiene.
2. **⚠️ Drift entre repo y instalación**: el add-on instalado tiene ruta correcta a `English_Automation_v2/` pero solo 2 hooks (faltan `profile_will_close`), mientras el repo tiene 3 hooks y ruta vieja. Llevan meses divergidos.

## 9. Decisiones acordadas con el dueño (2026-05-30)

| # | Decisión | Implementación |
|---|---|---|
| D1 | Rotar `NOTION_TOKEN` y eliminar secretos del add-on | Add-on lee `.env` con el mismo parser que ya está en el repo; documentar rotación en README |
| D2 | Add-on + watcher.sh redundantes a propósito | Lock de archivo en `run_all.py` (`fcntl.flock` sobre `logs/.pipeline.lock`); si está tomado, el segundo sale silencioso |
| D3 | `reset_used_today` nunca debe correr automáticamente | Quitar `reset` del pipeline `morning`. Solo `python3 run_all.py reset` manual |
| D4 | Errores por palabra en `anki_notion_sync` no deben abortar | try/except por palabra, contador `ok/fail`, log de las que fallaron al final |
| D5 | Eliminar drift repo ↔ Anki | `rm -rf` del add-on instalado + `ln -s` al `anki_addon/` del repo |
| D6 | Versionar el proyecto | `git init` local + `.gitignore` que cubra `.env`, `logs/*.log`, `.DS_Store`, `{anki_addon,scripts}/` |

**Confianza actual: ~92%.** Suficiente para empezar a implementar. Quedan dudas menores (timezone fija o configurable, formato exacto del `.gitignore`, si conviene `requirements.txt` ahora o después) que se pueden decidir en línea conforme aparezcan.

## 10. Orden de ejecución propuesto (cuando autorices)

1. **Seguridad primero** — rotar token en Notion → actualizar `.env` → editar add-on instalado para leer `.env` → reemplazar con symlink al repo.
2. **Anti-race** — añadir lockfile a `run_all.py` y borrar `reset` del pipeline morning.
3. **Robustez** — try/except por palabra en `anki_notion_sync.py` + paginación completa en `sync_used_words.py`.
4. **Higiene** — `git init`, `.gitignore`, borrar `{anki_addon,scripts}/`.
5. **(Opcional, después)** — `requirements.txt`, retry con backoff, validación de schema de Notion, rotación de logs.

