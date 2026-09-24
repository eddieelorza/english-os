# Prompts de las routines cloud (copias versionadas)

> Si editas un prompt en claude.ai/code/routines, actualiza aquí (y viceversa).
> Última revisión: 2026-08-04 — actividades interactivas de opción múltiple + los quizzes
> como detector gramatical: cada pregunta lleva su categoría en el toggle ('1. B — [Categoría] …')
> y la routine de corrección califica los checkboxes contra la clave, mandando cada fallo a
> Error Library con Source='Activity' (mismo bucle que los errores de writing). Comprehension
> se califica también (marca Reading Status=Done) pero no alimenta Error Library.

## "English Coach — Session Material" (`trig_01HvnwuNc1PinNW1gGnLQ2AE`)

Modelo claude-sonnet-5 · Conector Notion (solo) · Cron respaldo 03:30 UTC (21:30 CDMX).

**Principios del prompt vigente** (texto completo en la UI de la routine):

- **Filosofía de fricción**: Eddie se estresa con actividades de mucha escritura y
  entonces no las hace. Casi todo es **opción múltiple con checkboxes** (estilo
  Busuu); solo UNA actividad de escritura, corta. Eddie además usa Busuu Premium
  para drills genéricos — el valor único del sistema es material con SUS palabras,
  SUS errores (Target Errors) y SU nivel.
- **Reading**: historia 330-370 palabras, nivel = propiedad `Difficulty` del Daily
  Plan (B1 base; B1+ cuando los datos lo respaldan — regla en
  `daily_plan_update.recommend()`), palabras del día en negrita, Tense Focus
  frecuente. Comprehension = 4 preguntas de opción múltiple (párrafo + 3 `to_do`
  A/B/C) + toggle 🔑 Respuestas.
- **Writing**: en este orden —
  1. `📐 GRAMMAR — <Tense Focus>` (lee la propiedad `Tense Focus` de la página
     Writing; manda sobre cualquier rotación): callout de uso, tabla
     Forma|Ejemplo (afirmativo/negativo/pregunta/contracción con palabras del
     día), 3 bullets "cuándo se usa", callout ⚠️ "Trampa del español"
     (interferencia ES→EN), toggle 💡 con ejemplos de contexto profesional/PM.
  2. `🎯 ACTIVITY 1 — Grammar Quiz`: 6 preguntas de opción múltiple sobre el
     Tense Focus + Target Errors (elige la correcta / completa el hueco /
     encuentra el error), 3 `to_do` por pregunta + toggle respuestas con porqué.
  3. `🧩 ACTIVITY 2 — Vocabulary Check`: 4 huecos con palabras del día, opción
     múltiple + toggle respuestas.
  4. `✉️ ACTIVITY 3 — Mini Writing` (la única de escribir): 4-6 oraciones,
     Tense Focus ≥2 veces, banco de 5 palabras, recordatorio de marcar
     ☑ Ready for Review.
- Idempotencia por `AI Status=Done`; nunca toca `Status`/`Results`; nunca borra
  texto de Eddie; actualiza `Recommendation`.

## "English Coach — Review & Errors" (`trig_019tMdcUrsbByYZa9fT4obGc`)

Modelo claude-sonnet-5 · Conector Notion (solo) · Cron `0 20,4 * * *` (14:00 y
22:00 CDMX) · Manual: `run_all.py review` (requiere `ROUTINE_REVIEW_TOKEN`).

Protocolo vigente: busca Writing con `Ready for Review=true` y `Corrected=false`
(7d) → si no hay, sale sin tocar nada → **califica los checkboxes de los quizzes contra las claves de los toggles** (fallos →
Error Library con Source='Activity'; sesión de solo checkboxes es trabajo válido),
corrige el texto libre si lo hay (Mini Writing) → ≤8 errores categorizados + "Versión B2" + fortaleza/práctica →
1 fila por error en Error Library con dedup (`Recurrences += 1`) → cierra Writing
(`Corrected`, `Words Produced`, `Errors Count`) y escribe `Results` en Daily
Plan. Nunca toca `Status`.
