# Prompt — análisis de UI/UX de English OS

> Pégalo tal cual en una sesión nueva de Claude Code, en la raíz del repo.
> Solo analiza y propone: no edita código hasta que Eddie elija un camino.

---

/impeccable critique — la app completa (`frontend/src/`, las 10 lecciones)

## Qué quiero

English OS se construyó módulo a módulo (M1 → M22) durante un mes. Funciona,
pero se siente poco profesional. Quiero un diagnóstico con evidencia de **por
qué** se siente así y un plan para corregirlo, ordenado por impacto en el uso
diario, **no** una lista genérica de buenas prácticas.

"Más profesional" es la hipótesis que hay que traducir a problemas concretos.
No lo interpretes como "que parezca SaaS": `PRODUCT.md` lo prohíbe
explícitamente (Brand Commitments) y `DESIGN.md` define un mundo propio,
**The Assimil Workbook**. El análisis decide si el problema está en la
**ejecución** de ese mundo o en el **mundo** mismo, y me lo presenta como
decisión (paso 5).

## Paso 0 — Corrige el contexto antes de analizar

`PRODUCT.md` no se toca desde M1 y va a desviar el análisis. Estos datos
están mal:

- Eddie es **frontend engineer en Clip** (fintech mexicana), no product manager.
- Anki está **congelado** (ADR-011) y Notion **apagado** (ADR-012). El SRS es
  FSRS dentro de la app. "Anki now, FSRS later" y "Notion mirror" ya no aplican.
- "M1 (now): Vocabulary" → hoy hay **10 módulos construidos**: Today,
  Vocabulary, Reading (+ Reader), Podcast, Review, Practice, Writing,
  Speaking (+ conversación), Shadowing, Stats.
- Los números de "Evidence on Hand" son de agosto. Sácalos de
  `data/english.db` con consultas de solo lectura; no los copies.
- Falta una preferencia que pesa mucho en la UX: Eddie **abandona las
  actividades que exigen escribir mucho**. Opción múltiple, toggles y una
  sola escritura corta sí; producción libre larga no.
- Falta una restricción técnica: el LLM es local (Ollama `llama3.1:8b`) y en
  esta Mac de 16 GB tarda **de 15 a 80 s** por respuesta. Los estados de
  espera no son un detalle, son una parte central de la experiencia.

Propón el diff de `PRODUCT.md`, espera mi OK y luego sigue. `DESIGN.md` no se
toca en esta fase.

## Paso 1 — Arranca un sandbox que no toque mis datos

**Nada del análisis puede escribir en `data/english.db`.** Contestar una card
en Review reprograma FSRS de verdad. Cerrar una sentada encola el material del
día, lo duplica y lanza el LLM. Por eso:

```bash
cp data/english.db /tmp/english-ui-review.db
npm run build --prefix frontend
ENGLISH_DB_PATH=/tmp/english-ui-review.db \
ENGLISH_JOBS_LOCK=/tmp/english-ui-review.lock \
AI_PROVIDER=anthropic ANTHROPIC_API_KEY= ANTHROPIC_CONFIG_DIR=/nonexistent \
.venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port 8771
```

- El puerto 8771 sirve `frontend/dist` contra la **copia**. No uses Vite
  (5173): su proxy apunta a 8770, que es la base real.
- `AI_PROVIDER=anthropic` sin credenciales hace que la IA falle al instante,
  sin cargar el modelo. Así la RAM no explota y, de paso, ves los estados de
  "IA no disponible". El contenido ya generado se lee de la copia.
- Si una pantalla necesita IA para mostrarse, anótalo como hueco del
  análisis; no la fuerces.
- No grabes micrófono. En Speaking y Conversación analiza el estado inicial y
  el código.
- Al terminar, detén el server y borra `/tmp/english-ui-review.*`.

## Paso 2 — Recorre los flujos reales, no pantallas sueltas

Una pasada acotada: captura escritorio (1440 px, el escenario real: Mac por
la mañana) y ~390 px juntos, corrige la lista y confirma una vez más como
máximo. Los flujos, en orden de uso:

1. **La mañana**: Today → Review (una sentada completa: mostrar, calificar,
   intervalos) → cierre de sentada → vuelta a Today.
2. **Leer**: Reading (estante) → Reader → tocar una palabra → ¶ explicar
   oración → Listen & shadow → quiz de comprensión.
3. **Practicar**: Practice (drill) y Writing guiado (una oración a la vez).
4. **Escuchar y hablar**: Podcast, Speaking, Shadowing (estado inicial).
5. **Evidencia**: Stats y Vocabulary (búsqueda, filtros, expandir entrada).

En cada pantalla revisa también los estados **loading, vacío, error, espera
del LLM y pausa**, no solo el estado feliz.

## Paso 3 — Lentes de evaluación

**A. Coherencia entre módulos.** Es mi principal sospecha de lo que se siente
"amateur": diez módulos hechos en momentos distintos. Compara pantalla contra
pantalla la jerarquía de títulos, la anatomía de encabezado de lección, los
botones primarios y secundarios, el espaciado vertical, el copy y los estados
vacíos. Contrasta con las 10 *Committed rules* de `DESIGN.md` y di dónde se
rompen, con `archivo:línea`.

**B. Deuda medible.** Ya encontré estos puntos; verifícalos y dimensiónalos:
- `--color-ghost` (#8F8C83) sobre paper da **3.22:1**, por debajo de AA
  (4.5:1) para texto, y `text-ghost` aparece **145 veces**. ¿Cuántas son
  texto que hay que leer y cuántas decoración?
- La escala tipográfica son valores sueltos: `text-[10px]` ×52,
  `text-[11px]` ×53, `text-[12px]` ×81, más 13/14/15px. ¿Hay una escala real
  o ruido? Propón la escala.
- Motion: ¿se respeta la ley única (`SLIDE`, 0.32 s) o hubo deriva? ¿Existe
  `prefers-reduced-motion`?
- Navegación: la regla 10 hablaba de 01–06 y hoy son 10 lecciones. ¿El rail
  sigue funcionando como mapa del día, o ya es una lista larga?

**C. UX del hábito.** El guardarraíl del producto es ≥5 sesiones/semana.
Juzga cada pantalla por la pregunta **"¿me ayuda a empezar y terminar la
sesión de hoy sin fricción?"**: tiempo hasta la primera acción, claridad de
qué sigue, teclado en Review, feedback inmediato y la espera del LLM
(¿se entiende qué pasa?, ¿puedo hacer otra cosa mientras?).

**D. Accesibilidad y robustez.** Foco visible y orden de tab, labels en
botones con solo ícono, `lang="es"` en el contenido en español, targets,
responsive a 390 px y texto que desborda.

## Paso 4 — Entregable

Un reporte en `docs/ui-ux-review.md` con:

1. **Veredicto en 5 líneas**: qué hace que se sienta poco profesional, dicho
   sin rodeos.
2. **Top 10 problemas**, ordenados por impacto en el hábito diario. Cada uno
   con: captura, pantallas afectadas, `archivo:línea`, la regla de
   `DESIGN.md` o la heurística que rompe, la propuesta concreta y el
   esfuerzo (S/M/L).
3. **Scorecard por lección** (01–10) con las heurísticas de `critique`.
4. **Lo que ya está bien**, para no romperlo al corregir.
5. **Huecos**: lo que no se pudo evaluar y por qué.

## Paso 5 — La decisión (opción múltiple, no me pidas redactar)

Termina con esta pregunta, con evidencia a favor y en contra de cada opción y
tu recomendación:

- **A. Pulir el mundo actual.** Mismo Assimil Workbook, ejecución consistente:
  escala tipográfica, contraste, componentes compartidos y estados.
  `polish` · `typeset` · `layout` · `clarify` · `harden`.
- **B. Evolucionar el mundo.** Se mantiene el concepto, pero se ajustan tokens,
  tipografía o navegación, y se actualiza `DESIGN.md`.
  `typeset` · `layout` · `extract` · `adapt`.
- **C. Rediseñar.** El workbook no da para lo que es hoy la app; se elige un
  mundo nuevo vía `new-work` y se reemplaza `DESIGN.md`. Sigue siendo
  "lectura/estudio" (Kindle, Readwise Reader, LingQ), nunca SaaS.

Para la opción recomendada, incluye un plan por fases (cada fase = un comando
de impeccable + las lecciones que toca + un criterio de "terminado").

## Reglas

- No edites código ni `DESIGN.md` en esta sesión. Solo `PRODUCT.md` (con mi
  OK) y el reporte.
- Nada de commits; yo los confirmo.
- La UI queda en inglés; el español se muestra solo cuando se pide. Nada de
  gamificación punitiva ni de métricas inventadas ("not enough data" cuando
  aplique).
- Si dudas entre dos lecturas, pregúntame con opciones cortas.
