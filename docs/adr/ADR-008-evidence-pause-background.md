# ADR-008 — Fase 3: evaluación multi-evidencia, pausa, cola de fondo y Practice viva

> Estado: **aceptado** (2026-08-21, decisiones de Eddie por opción múltiple).
> Extiende [ADR-006](ADR-006-english-os-local-first.md) y
> [ADR-007](ADR-007-audio-practice-phase2.md). Milestones M12–M15.

## Contexto

Con la Fase 2 en uso, Eddie levantó cuatro cosas. Tres son mejoras; la cuarta
destapó **un fallo de diseño real**, verificado en código antes de escribir
este ADR:

1. **No hay pausa.** Si no puede estudiar, las cartas se acumulan, la racha se
   rompe y el material diario se genera igual, para nadie.
2. **La IA bloquea y calienta.** Toda generación es HTTP síncrono: pide un
   podcast y espera ~100 s mirando un spinner. Peor: dos generaciones a la vez
   corren **dos inferencias en paralelo** peleándose el CPU.
3. **Practice es estática.** Seis preguntas de golpe, feedback solo al final —
   además de aburrido, es pedagógicamente peor que el feedback inmediato.
4. **La evaluación depende de escribir.** `recommend_level` exige
   `errors_per_100` para conceder B2, y ese número requiere ≥150 palabras
   escritas en 14 días: **sin escribir, el techo del sistema es B1+ para
   siempre**, por bien que vaya en todo lo demás. Y encima, la evidencia que
   genera *sin esfuerzo* se descarta: los quizzes de comprensión de lectura y
   de podcast **no se guardan** — justo el dato de los días en que no quiere
   escribir.

## Decisiones

| # | Decisión | Alternativas descartadas |
|---|---|---|
| D1 | **Evaluación multi-evidencia**: el nivel se calcula con lo que haya (recall, comprensión, precisión en actividades, producción libre = writing **o** speaking), no exigiendo una fuente concreta. Cada veredicto declara en qué se basó. | Seguir exigiendo writing (deja días ciegos); ponderación fija (castiga al que varía su práctica). |
| D2 | **Capturar la comprensión**: los quizzes de lectura y podcast se califican y persisten. Es evidencia de bajo esfuerzo, y hoy se tira. | Dejarlos client-side. |
| D3 | **Pausa que cubre app y Anki** (AnkiConnect pospone las cartas). Al reanudar, el rezago se reparte en una rampa, no cae de golpe. Los días pausados **no rompen la racha** (Vision §5: el sistema debe sobrevivir la desmotivación). | Pausa solo in-app; dejar que se acumule. |
| D4 | **Cola de trabajos serializada**, una tarea a la vez, con estado consultable. Elimina el paralelismo de inferencias — la causa real del sobrecalentamiento. | Correr en paralelo; seguir bloqueando la petición HTTP. |
| D5 | **Pre-generación al cerrar Anki**, reusando el gancho `session-end` existente: al abrir la app, el material del día ya está escrito. | Cron de madrugada (la Mac puede estar dormida); solo bajo demanda. |
| D6 | **Obsidian archiva todo**: una nota por día con lo hecho y cómo salió, más lecturas, writings con su corrección, podcasts y actividades, enlazados al perfil. | Seguir exportando solo perfil/errores/palabras. |
| D7 | **Practice de una pregunta a la vez**, feedback inmediato, progreso visible. Cinético, pero dentro del mundo Assimil — sin mascotas ni confeti. | Mantener la lista estática; copiar Duolingo literalmente. |

**Honestidad sobre D4**: mover la generación a segundo plano **no reduce el
calor total** — es el mismo cómputo. Reduce (a) la espera con el ventilador
al máximo delante, y (b) los picos por inferencias simultáneas. Se documenta
así para no vender lo que no es.

## Milestones

### M12 — Evaluación multi-evidencia + archivo completo en Obsidian
- Persistir resultados de comprensión (lectura y podcast) — nueva tabla o
  columnas en `texts`; endpoints de submit.
- `model.evidence(conn)`: recall, comprensión, precisión controlada,
  producción libre (writing **+** speaking sumados), cada una con su tamaño de
  muestra y su regla de honestidad.
- `recommend_level` reescrito sobre esa evidencia; el `reason` nombra las
  fuentes usadas. Sin writing, el nivel sigue siendo evaluable.
- `obsidian.export` amplía a `Days/`, `Readings/`, `Writings/`, `Podcasts/`.
- Criterio: una semana sin escribir nada y el sistema aún emite un nivel
  fundamentado; el vault refleja lo que hizo cada día.

### M13 — Pausa (app + Anki)
- Tabla `pauses`; la cola SRS y la generación respetan la pausa.
- Al reanudar: recorrer vencimientos y repartir el rezago en rampa.
- Racha: días pausados neutrales, no rotos.
- AnkiConnect: posponer cartas en el mismo gesto (best-effort, nunca fatal).
- Criterio: pausar cinco días y volver sin muro ni racha rota.

### M14 — Cola de trabajos en segundo plano
- `app/jobs.py`: cola serializada en proceso, estado por trabajo, endpoint de
  consulta. Generación de lecturas, podcasts y actividades pasan por ahí.
- Pre-generación del día siguiente en `session-end`.
- UI: "se está escribiendo" sin bloquear la navegación.
- Criterio: pedir lectura y podcast a la vez ejecuta una tras otra; abrir la
  app por la mañana con el material listo.

### M15 — Practice viva
- Una pregunta a la vez, feedback inmediato con su porqué, progreso, cierre
  con resultado. Mismo mundo visual.
- Criterio: una sesión se siente rápida y responde al instante.

## Riesgos

| Riesgo | Mitigación |
|---|---|
| Cambiar la regla de nivel altera veredictos históricos | El nuevo `reason` declara siempre sus fuentes; los datos crudos no se tocan. |
| Posponer cartas en Anki modifica su colección | Best-effort y explícito: si AnkiConnect no responde, la pausa in-app sigue valiendo y se avisa. |
| Cola en proceso muere al reiniciar el server | Estado en SQLite; los trabajos perdidos se re-encolan al arrancar. |
| Pre-generar gasta CPU aunque no estudie ese día | Solo corre tras una sesión real de Anki (ya hay compuerta `MIN_SESSION_REVIEWS`). |
