# ADR-016 — Menos API, más contexto: lecturas por rutina, cadenas por tarea, huecos del mazo

- **Estado**: implementado y probado (2026-09-21); la rutina de Claude Code **no está creada** todavía.
- **Contexto**: continúa ADR-015 D7 (IA híbrida)
- **Decide**: Eddie (reparto de trabajo); análisis e implementación Claude

## Lo que se midió

| Dato | Valor |
|---|---|
| Gasto de Claude API en todo el día de pruebas | $0.01 (4-5 llamadas, $0.0003-0.0016 cada una; una lectura completa $0.005) |
| Lecturas sin leer | **97 de 102** — generar más no era el cuello de botella |
| ¿Una lectura ya existente cubre las palabras de hoy? | No: salvo las 2 de hoy, la mejor cubría 6 de 12 |
| Palabras con oración de ejemplo del mazo | 2,398 |
| Llamada mínima al CLI `claude -p` (sin `ANTHROPIC_API_KEY`) | 12.4 s y ~47,000 tokens de sobrecarga (~$0.05 a precios de API) vs $0.0003 directa |

Conclusión: el dinero ya no es el problema (Claude API quedó como último respaldo con tope de
10 llamadas y $0.05/día). Lo que queda por ganar es **calidad, espera y cómputo inútil**.

## Decisiones

### D1 — Una sola regla para "¿toca generar lectura?" (`generator.skip_reason`)
No si el día ya tiene una; no si hay una sin leer de los últimos 3 días. La usan el trabajo
diario de la app (`jobs.enqueue_daily`, al cerrar una sentada) y la rutina. Lo que nadie lee es
cómputo gastado.

### D2 — Vocabulario en contexto sin modelo (`activities._cloze`)
`vocabulary_check` se construye con las oraciones de ejemplo del mazo (hechas por una persona),
para las palabras que más falla (`model.learning_words`). El modelo escribe la actividad solo si
hay menos de 3 oraciones utilizables. Con las palabras reales de hoy: 11 de 16 sirven.
- Solo sirven oraciones donde la palabra aparece tal cual y una vez (con "forged" la opción base
  "forge" desencajaría).
- Los distractores se prefieren entre palabras que en su propia oración van tras el mismo tipo de
  palabra (artículo, "to", "was/very"): sin etiquetador gramatical es la única pista disponible.
  Límite: puede quedar algún distractor que no encaje; el ejercicio es de significado y contexto.
- Límite: la oración es la misma que ves en la tarjeta de Review, así que parte del acierto puede
  ser memoria de la frase y no del significado.

### D3 — Cadenas por tarea (`AI_CHAIN_<TAREA>`)
Manda sobre la de su clase; el trabajo en lote (`glossary`) sigue siendo solo local.
Reparto actual: material generado → Gemini, Ollama · podcast → Ollama · writing, speaking,
conversación, explicar → Ollama, Claude API solo si Ollama falla.

### D4 — La lectura puede escribirla una rutina de Claude Code (usa el plan, no la API)
`GET /api/reading/brief` entrega lo mismo que recibiría el generador local (reglas, esquema,
palabras, nivel) y `POST /api/reading/submit` valida con las mismas reglas: palabras objetivo,
250-450 palabras, prosa plana, 4 preguntas de 3 opciones. 409 si el día ya tiene lectura.
La rutina no toca la base ni el código.

**Por qué no un proveedor `claude -p` dentro del enrutador:** 12 s y ~47k tokens por llamada
quemarían el cupo del plan en llamadas cortas. Como rutina de una corrida al día sí es razonable.
Si algún día se usa el CLI desde la app, el subproceso debe correr **sin** `ANTHROPIC_API_KEY`,
o cobra a la API en vez de usar el plan.

### D5 — Podcast y práctica también los puede escribir Claude Code (2026-09-21)
Lo mismo que D4, generalizado en `app/routine.py`: `GET /api/routine/brief/{reading|podcast|practice}`
y `POST /api/routine/submit/{kind}`. El `brief` entrega el mismo `system`/`prompt`/`schema` que
recibiría el modelo local, más `skip` (la regla D1, ahora por tipo de material: `generator.skip_reason(conn, day, kind)`).
El `submit` valida con el mismo código que usa la app — preguntas de comprensión
(`generator.check_questions`), preguntas de práctica (`activities.clean_questions`), diálogo de 14+
turnos — así que un texto flojo se rechaza con el motivo, no se guarda a medias.

- Coste: **0 tokens de API y 0 inferencia local** para el texto. Lo único que sigue costando CPU es
  el audio del podcast (Kokoro), y corre dentro de `jobs.exclusive()`: nunca dos inferencias a la vez.
- Una práctica ya contestada no se pisa; una sin contestar sí se reemplaza.
- Medido hoy: Gemini vivo (`gemini-flash-lite-latest`, 3.2 s con el esquema real de lectura, 323/677
  tokens), así que la cadena `gemini,ollama` sigue siendo el respaldo automático cuando nadie escribe a mano.

## Compromisos
- Una rutina ahorra casi nada de dinero (medio centavo al día); su valor es la calidad y que la
  lectura esté lista antes de sentarse. Necesita la app de Claude abierta (si no, corre al abrirla).
- Con la regla D1, si no lees, no se genera más: puede pasar días sin material fresco.

## Pendiente
- Crear la rutina (hora sugerida: 5:00, tras el cambio de día de estudio a las 4:00).
- Valorar que la rutina escriba también actividades y consejo en la misma corrida, para repartir
  la sobrecarga de ~47k tokens.
