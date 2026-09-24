# ADR-002 — Bucle mínimo de entrenador

> Estado: **diseño aprobable** (2026-07-29). Fase 1 implementa el sustrato
> (Daily Plan + recomendación por reglas); la captura de resultados de writing
> llega en Fase 2 con Error Library.

## El bucle

```
actividad ──► resultado ──► Learner Profile ──► decisión ──► siguiente actividad
   │              │               │                 │                │
 Anki,        Anki stats,   data/learner_     reglas v0        fila Daily Plan
 Reading,     Corrected,    profile.json     (+ Claude si      + sección TODAY
 Writing      errores(F2)   (+ Notion)        hay API key)     + material del día
```

Un solo archivo de estado (`data/learner_profile.json`) y un solo punto de
decisión (`recommend()` en `daily_plan_update.py`). Sin agentes múltiples aún.

## Qué se puede medir YA (implementación actual)

| Métrica | Fuente | Estado |
|---|---|---|
| Reviews/día, palabras nuevas/día, again rate | AnkiConnect (`getNumCardsReviewedToday`, `introduced:1`, `rated:1:1`) | ✅ capturándose desde ADR-001 |
| Palabras sincronizadas/día | VOCAB `Synced On` | ✅ |
| Sesión completada (proxy) | Writing `Corrected` checkbox | ✅ existe, lo marca el flujo "revísame" |
| Palabras usadas en ejercicios | VOCAB `Used Today` / `Times Used` (sync-used) | ✅ existe (actividad, no calidad) |
| Racha / frecuencia de sesiones | `learner_profile.json` días con entrada | ✅ |
| Ease/lapses por palabra (dificultad de reconocimiento) | VOCAB `Ease`/`Lapses` | ✅ ya sincronizado |

## Qué NO se puede medir todavía (y qué falta para cada una)

| Métrica | Falta |
|---|---|
| **Errores por categoría y por 100 palabras** | Que la corrección (flujo "revísame") escriba resultados estructurados → Error Library (F2). Hoy la corrección se pierde como prosa. |
| Comprensión de Reading | Preguntas con resultado registrado (prop `Comprehension %` en Reading Hub, F3) |
| Recall productivo | Warm-up productivo con score (F3) |
| Uso correcto en contexto (vs solo "usada") | Evaluación de la corrección por palabra (F2/F3) |
| Todo speaking/listening | Motores M4/M1 (posterior) |

## El cambio mínimo para empezar a saber si Eddie mejora

**Uno solo: estructurar la salida de la corrección.** El flujo "ya terminé,
revísame" ya existe y ya lo hace Claude a diario — solo tira la información.
En F2, ese flujo además de corregir: (1) crea una fila por error en Error
Library `{categoría, original, corrección, fuente, fecha}`, (2) escribe
`{errores_totales, palabras_producidas}` en la fila Daily Plan (→ errores/100
palabras, la métrica más predictiva disponible), (3) anota el resumen en
`learner_profile.json`. Cero fricción nueva para Eddie: el dato es subproducto
de una corrección que ya ocurre (Vision P2).

## Decisión: reglas v0 (sin API key) — determinista y suficiente

`recommend(profile, plan_history)` produce la recomendación de mañana:

1. `again_rate > 20%` (3 días ventana) → bajar palabras nuevas, sesión de repaso.
2. `Corrected = false` en ≥2 sesiones recientes → mañana prioridad: corrección
   pendiente antes de material nuevo.
3. Racha < 3 sesiones/últimos 7 días → sesión ligera (proteger hábito, Vision §5).
4. Rotación de formato: no repetir el `Format` de ayer (lista: Story, Dialogue,
   Spot & Fix, Free Writing, Role Play, Email, Opinion).
5. (F2+) categoría de error dominante de la semana → `Target Errors` de mañana.

Cuando exista `ANTHROPIC_API_KEY`, Claude recibe el mismo input y puede
**refinar** el output de las reglas (mejor prompt de writing, foco más fino);
si la llamada falla o no hay key, el sistema usa las reglas tal cual. La API
mejora decisiones, nunca es dependencia dura.
