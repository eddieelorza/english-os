# ADR-007 — Fase 2: audio, práctica interactiva y podcast

> Estado: **aceptado** (2026-08-21, decisiones de Eddie por opción múltiple).
> Extiende [ADR-006](ADR-006-english-os-local-first.md) (roadmap M0–M7 completo)
> con la Fase 2: M8–M11. No cambia ninguna decisión de ADR-006.

## Contexto

Con el English OS funcionando (las seis lecciones vivas), Eddie pidió cerrar
las brechas que impiden usarlo como su sistema único: no hay audio (ni para
pronunciación ni para shadowing), no hay práctica interactiva tipo Busuu ni
writing dentro de la app, el reader solo explica palabras (no oraciones), el
material se acumula sin orden por día, y falta el formato podcast que le
sensibiliza el oído (referencia: English Leap Podcast).

**Hallazgo que cambia el plan**: su mazo `Essential_English_Words_en-es.apkg`
(compartido 2026-08-21) contiene **7,188 MP3s** — audio por palabra
(`01_0001.mp3`) *y* por oración de ejemplo (`01_0001_example.mp3`) — más
**3,593 imágenes**, en 3,602 notas. Es exactamente el deck del que salió su
AJ-Basic vivo, así que mapea por texto a la tabla `words`. **La pronunciación
por palabra no se genera: se importa**, y es el audio que su oído ya reconoce.

## Decisiones

| # | Decisión | Alternativas descartadas |
|---|---|---|
| D1 | **TTS: Kokoro local** (~330MB en el venv) para lecturas y podcast. Varias voces EN → cubre el diálogo a dos voces. | macOS `say` (robótico en prosa larga); edge-tts (cloud, rompe local-first D1 de ADR-006). |
| D2 | **Audio de palabras: importado del apkg**, no generado. Media a `data/media/` (gitignored). | Generar todo con TTS (peor: pierde el audio que ya conoce). |
| D3 | **Importar también las imágenes** (~160MB total con audio) para flashcards y slips más memorables. | Solo audio. |
| D4 | **Orden M8→M9→M10→M11**: audio primero porque desbloquea listening (M9) y podcast (M11). | Empezar por actividades u orden. |
| D5 | Las actividades interactivas **portan la filosofía de `docs/routine-prompt.md`** (opción múltiple, checkboxes, una sola actividad de escritura corta) — probada con Eddie durante meses. | Diseñar un formato nuevo. |
| D6 | Los fallos de actividades y las correcciones de writing **alimentan la misma tabla `errors`** (`Source='Activity'`/`'Writing'`) que ya usan Speaking y la routine cloud. Un solo bucle. | Tablas separadas por módulo. |

## Milestones

### M8 — Fundación de audio
- `app/importers/apkg.py`: descomprime el `.apkg`, mapea `notes.flds` → palabra,
  copia media a `data/media/{audio,images}/`, guarda rutas en `words`
  (`audio_word`, `audio_example`, `image_path`).
- `app/tts.py`: `TTSProvider` desacoplado (misma forma que `AIProvider`) con
  `KokoroProvider` + fallback `SayProvider`; caché por hash de texto+voz en
  `data/media/tts/`.
- Endpoint `/api/media/{tipo}/{archivo}`; 🔊 en Vocabulary, Review y el slip
  del Reader; audio de lectura con **karaoke por oración**, velocidad 0.8×/1×
  y toggle "ahora leo yo".
- Criterio: escuchar una lectura completa con resaltado, y oír cualquier
  palabra del ledger con el audio del mazo.

### M9 — Práctica interactiva
- `app/activities.py`: generador de sets diarios (grammar quiz sobre el tense
  focus, vocabulary check, match, **listening con los MP3s del mazo**).
- `app/writing.py`: prompt del modelo → editor con contador de palabras y
  tiempo en vivo → corrección con el protocolo de la routine + **análisis de
  tiempos verbales usados** vs el foco del día.
- **Consejo de gramática rápida** al cierre de cada evaluación diaria, generado
  desde el error más recurrente (3-4 líneas, sin teoría innecesaria).
- Criterio: una sesión completa de actividades + un writing corregido, con los
  fallos visibles en Stats al día siguiente.

### M10 — Reader plus + orden
- Selección de **oración** → explicación de contexto + gramática + equivalente
  natural en español (caché por oración).
- Shelves **agrupados por día** en Reading, Writing y Activities; borrar
  (con confirmación) y archivar material generado por error.
- Criterio: encontrar lo del martes pasado en dos clics; borrar una lectura
  mal generada sin tocar la base a mano.

### M11 — Podcast studio
- Diálogo natural entre dos personas tejiendo las palabras en aprendizaje
  (estilo English Leap: explicaciones intercaladas), producido con **dos voces**
  Kokoro.
- **Dos modos**: *shadowing* (transcript con karaoke, velocidad, pausa por
  turno) y *oído* (solo audio, sin transcript, quiz de comprensión al final).
- Criterio: un episodio de ~5 min escuchable sin leer, con quiz que se pueda
  responder solo habiendo escuchado.

## Riesgos

| Riesgo | Mitigación |
|---|---|
| Peso del media (~160MB) | `data/media/` gitignored, igual que `english.db`; import idempotente. |
| Calidad/latencia de Kokoro en prosa larga | Caché agresivo por oración; generar en background y avisar cuando esté listo. |
| qwen2.5:7b corto para diálogos de podcast | Mismo camino que las lecturas: retry-pass o `ANTHROPIC_API_KEY` cuando Eddie quiera. |
| Fricción de escritura (Eddie se frena) | D5: una sola actividad de escritura corta por sesión; el resto opción múltiple. |
