# Auditoría de la estructura Notion — ENGLISH SYSTEM

> Fecha: 2026-07-29. Inspección vía API (solo lectura) previa a la Fase 1.
> Backup de estructura: `backup-2026-07-29.json` en este directorio.

## 1. Páginas y bases existentes

Página principal `ENGLISH SYSTEM` (`2f6fd5e5f5a98021907be60603639ea1`):

| Elemento | Tipo | Estado |
|---|---|---|
| VOCABULARY MASTER (`2f7f…1776`) | DB | **Producción** — el pipeline escribe aquí |
| Writing Practice (`2f8f…6c55`) | DB | **Producción** — 60 páginas |
| Reading Hub (`2f9f…e048`) | DB | **Producción** — 62 páginas |
| Study Log (`2f9f…fd4f`) | DB | Proto-dashboard semanal: relaciones a VOCAB/Writing/Reading + rollups + fórmulas. Aparentemente manual/template. |
| Weekly Routine (`2f9f…6f02`) | DB | Checklist semanal manual (checkboxes Anki/Writing/Listening/Reading/Speaking) |
| Untitled (`2faf…8078`) | DB | **Vacía, sin propiedades** — basura de template |
| 📈 Progress Tracker | Página | Manual, desactualizada (última evaluación 2026-04-07). Contiene: nivel B1/A2+, tabla de errores frecuentes, objetivos |
| 📋 PROMPT — Claude English Assistant | Página | El prompt manual que define las 4 actividades actuales (Spot & Fix, Dialogue, Free Writing, Grammar Spotlight) |
| 🎭 Role Play — PM English | Página | 8 escenarios de role play PM + frases clave |
| Listening / Grammar | Páginas | Contenido manual |
| 2 páginas de notas personales (trabajo/liderazgo) | Páginas | **Fuera del sistema de inglés — no se tocan** |

## 2. Hallazgos importantes (drift código ↔ Notion)

1. **`Last Reviewed` en VOCAB es tipo `last_edited_time`**, no `date`. El código
   (`anki_notion_sync.build_props`, `writing_session_daily`) la trata como date.
   Empíricamente funciona (24 palabras con `Synced On`=hoy), pero la semántica del
   filtro "palabras de hoy" ahora es "páginas *editadas* hoy" — cualquier edición
   manual de una palabra vieja la mete al día. **Los nuevos scripts usan `Synced On`**
   (registro propio del pipeline, tipo `date` real).
2. Propiedades en Notion que el código no conoce: `LEAR STATUS` (status),
   `Sync Run` (rich_text) en VOCAB; `Minutes`, `Sentences Count`, relación `Word(s)`
   en Writing; `Level`, `Status` en Reading. Nadie las llena automáticamente hoy.
3. Las actividades diarias reales las define el **prompt manual**, que reemplaza los
   ejercicios del script («NO conserves los ejercicios del script»). Es decir: el
   generador de ejercicios de `writing_session_daily.py` ya está siendo descartado a
   diario por diseño de Eddie. Confirmación práctica del principio P5 (eliminar lo
   que no enseña) — se formalizará en fases posteriores, no ahora.

## 3. Qué se conserva sin cambios

- VOCABULARY MASTER: schema y sincronización intactos (restricción dura).
- Writing Practice y Reading Hub: DBs, IDs, títulos y generación diaria intactos.
- Study Log, Weekly Routine, Progress Tracker, PROMPT, Role Play, Listening, Grammar,
  notas personales: **sin tocar en Fase 1**.

## 4. Qué se reorganiza (Fase 1: nada destructivo)

- Se inserta una sección **🎯 TODAY** (callout mantenido por el pipeline,
  reconstruida idempotentemente en cada session-end) al inicio de la página principal.
- Nada se mueve ni se borra. Reorganización visual mayor: fases posteriores, con
  aprobación explícita.

## 5. Nuevas bases realmente necesarias

| DB | Fase | Justificación |
|---|---|---|
| **Daily Plan** | **1** | La página-por-sesión que pide Eddie; sustrato del bucle entrenador |
| **Error Library** | 2 | Registro estructurado de errores reales (hoy solo existen como tablas manuales en Progress Tracker) |
| Ninguna más por ahora | — | Reading Library = Reading Hub mejorado (props, no DB nueva). Practice Hub = página con vistas, no DB. Learner Profile/Progress = página + `data/learner_profile.json`, no DB. Settings = página con una DB mínima si hace falta. **Evitar proliferación de DBs.** |

## 6. Propiedades nuevas por base

**Daily Plan** (nueva): `Session` (title), `Date`, `Status` (Pendiente/En progreso/
Completada), `Skill`, `Difficulty`, `Format`, `Words Today` (number), `Anki Reviews`
(number), `Again Rate` (number), `Target Errors` (rich_text), `Reading` (relation→
Reading Hub), `Writing` (relation→Writing Practice), `Results` (rich_text),
`Recommendation` (rich_text).

**Fases posteriores** (no ahora): Reading Hub + `Topic`, `Comprehension %`,
`Daily Plan` (relation); VOCAB + `Productive Status` (select: Reconocida / Recall
productivo / Usada en contexto / Adquirida) — **propiedad nueva, sin tocar las existentes**.

## 7. Relaciones y rollups

Fase 1: Daily Plan → Reading Hub y Daily Plan → Writing Practice (relations).
Posterior: Error Library → Daily Plan; rollups de errores/semana en Study Log
(reutilizando el proto-dashboard existente en vez de crear otro).

## 8. Cambios en el pipeline

- `scripts/daily_plan_update.py` (nuevo): upsert de la fila Daily Plan del día +
  reescritura idempotente de la sección 🎯 TODAY + recomendación por reglas (v0 sin
  API key; Claude la mejora cuando exista `ANTHROPIC_API_KEY`).
- `run_all.py session-end`: nuevo paso al final. Si falta `DAILY_PLAN_DB_ID` en
  `.env`, el paso se salta con log (no rompe el pipeline).
- `.env`/`.env.example`: `ENGLISH_SYSTEM_PAGE_ID`, `DAILY_PLAN_DB_ID`.

## 9. Riesgos de migración

| Riesgo | Mitigación |
|---|---|
| Tocar la página principal rompe el layout del template | La sección TODAY es UN bloque callout insertado tras el primer divider; borrado/recreación solo de ese bloque, identificado por marcador `🎯 TODAY`. Backup JSON previo. |
| API de Notion **no puede crear vistas** de DB (linked views, filtros, orden) | Las vistas se especifican en doc y Eddie las crea en 5 min de UI, o se usa el conector Notion de claude.ai (soporta create-view) si Eddie lo autoriza. No se fuerza. |
| Duplicar filas Daily Plan | Upsert por `Date` = hoy; mismo patrón probado de Writing/Reading. |
| Drift de schema futuro (alguien renombra una propiedad) | Igual que hoy (riesgo preexistente); la validación de schema al arranque sigue en deuda técnica. |
| Reversibilidad | Borrar el callout TODAY + archivar Daily Plan DB = estado anterior exacto. Nada existente se modifica. |

## 10. Plan por fases

- **F1 (ahora)**: sección TODAY + Daily Plan DB + integración pipeline + spec de vistas para Vocabulary/Reading/Writing. Criterio: abrir Notion tras estudiar y encontrar todo listo sin comandos.
- **F2**: Error Library + captura de resultados del flujo "revísame" (cierra el bucle entrenador — ver ADR-002).
- **F3**: vistas de Vocabulary Master por estado productivo, props de Reading Hub (Topic/Comprehension), Practice Hub con vista Today.
- **F4**: Learner Profile page + Progress dashboard (Python calcula, Notion muestra) + Weekly Review automático.
- **F5**: Settings + planner con Claude (reglas siempre como fallback).

Cada fase se valida contra la rutina real de Eddie antes de pasar a la siguiente.
