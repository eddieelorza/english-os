# ADR-004 — Error Library: la corrección se vuelve dato (Fase 2)

> Estado: **implementado** (2026-07-29). Cierra el bucle entrenador descrito en
> ADR-002: hasta hoy la corrección diaria se producía y se tiraba.

## Problema

El flujo "ya terminé, revísame" ya ocurría todos los días y ya generaba
exactamente la información más predictiva del avance hacia B2 (errores por
categoría, errores/100 palabras). Pero vivía como prosa en una página de Notion:
irrecuperable, no agregable, invisible para el planificador. `Target Errors` del
Daily Plan estaba **hardcodeado** con una lista semilla.

Además era el último paso manual de la rutina: exigía abrir un chat.

## Decisión

Dos piezas, siguiendo la separación de ADR-003 (Claude = cognitivo, Python =
determinístico):

**1. Routine de corrección** (`trig_019tMdcUrsbByYZa9fT4obGc`, "English Coach —
Review & Errors", Sonnet, conector Notion, cron `0 20,4 * * *` = 14:00 y 22:00
CDMX). Disparo: su propio cron, o `python3 run_all.py review`.

```
Eddie escribe en la página Writing  ──►  marca ☑ "Ready for Review"
                                              │
                              (cron 14:00 / 22:00, o run_all.py review)
                                              ▼
   Routine: busca Writing con Ready=true Y Corrected=false (7d)
     · si no hay → "Nada que corregir", sale sin tocar nada
     · corrige SOLO lo que escribió Eddie, añadiendo al final (nunca borra)
       → lista de ≤8 errores [CATEGORÍA] original → corregida — por qué
       → párrafo "Versión B2" del mejor párrafo suyo (noticing the gap)
       → 1 fortaleza + 1 cosa a practicar
     · Error Library: 1 fila por error, con dedup (mismo patrón + categoría →
       Recurrences += 1, Priority sube: 3+ = Alta)
     · Writing: Corrected=true, Ready=false, Words Produced, Errors Count
     · Daily Plan: Results = "18 errores/312 palabras — Preposiciones 6, …"
       (nunca toca Status, que es de Eddie)
```

**2. `scripts/error_metrics.py`** (Python, determinístico). Agrega Error Library
+ Writing de los últimos 14 días y produce las dos señales que el planificador
necesita: `top_categories` y `errors_per_100`. Se guarda en
`data/learner_profile.json` (serie temporal) y alimenta:

- `Target Errors` del Daily Plan → **ahora es dato real**, no semilla. Lo consume
  la routine de material al generar la Activity 1 (Spot & Fix) del día siguiente:
  practicas tus errores reales, no una lista genérica.
- La recomendación por reglas ("Foco de hoy: Preposiciones…").
- El callout 🎯 TODAY: `📊 Precisión (14d): X errores/100 palabras · Foco: …`.

**Honestidad de datos** (Vision P4): con menos de 150 palabras producidas en la
ventana, `errors_per_100` es `None` y la UI muestra **"Sin datos suficientes"**.
Nunca un número inventado.

## Nuevas estructuras en Notion (todo aditivo)

- **Error Library** (`ERRORS_DB_ID`): Error (title), Category (13 opciones),
  Original, Correction, Explanation, Source, Date, Recurrences, Status,
  Priority, Last Practiced, relación → Daily Plan.
- **Writing Practice** +3 propiedades: `Ready for Review` (checkbox),
  `Words Produced`, `Errors Count`. No se modificó ni eliminó nada existente.

## Hallazgo de implementación

**Los trigger tokens son por routine, no por cuenta.** Reusar el token de la
routine de material contra la de corrección devuelve `401`. Por eso
`fire_routine()` ahora recibe qué variable de token usar
(`ROUTINE_FIRE_TOKEN` / `ROUTINE_REVIEW_TOKEN`).

## Qué NO se hizo (deliberadamente)

- **Cards de Anki con los errores** (M3 de REDESIGN.md). La routine cloud no
  puede hablar con AnkiConnect, y el valor pedagógico ya se captura vía
  `Target Errors` → Activity 1 del día siguiente. Si tras un mes los datos
  muestran categorías que no ceden, se implementa en Python (leer Error Library
  → `addNote`). No antes: sería duplicar la práctica sin evidencia de que hace falta.
- Corrección de speaking: no hay speaking todavía (Fase 4+).

## Riesgos

1. **La routine confunde texto de Eddie con texto del sistema** y corrige
   enunciados. Mitigado por instrucción explícita + regla dura de no borrar;
   verificable en la primera corrección real.
2. **Dedup difuso**: "mismo patrón" lo juzga el modelo; puede crear duplicados o
   fusionar de más. Aceptable: el conteo por categoría (lo que alimenta al
   planner) es robusto a errores de dedup individuales.
3. **Doble corrección** si Eddie marca el checkbox otra vez tras corregir:
   evitado por el guard `Corrected=false`.
4. `Ready for Review` es un clic manual. Es el único paso que queda, y es
   deliberado: solo Eddie sabe cuándo terminó de escribir.

## Criterios de aceptación

1. Escribes en la página Writing, marcas ☑ Ready for Review, y sin hacer nada más
   la corrección aparece esa misma tarde/noche, con errores categorizados. ✅ ruta
   de guard verificada (sin nada marcado → 0 escrituras); pendiente la primera
   corrección real con texto tuyo.
2. Los errores aparecen como filas en Error Library, y repetir un error sube
   `Recurrences` en vez de duplicar fila.
3. Al día siguiente, `Target Errors` del Daily Plan y la Activity 1 apuntan a tu
   categoría de error más recurrente.
4. Con Error Library vacía, todo el sistema sigue funcionando y muestra
   "Sin datos suficientes". ✅ verificado.
5. La routine nunca borra ni reescribe lo que escribiste.
