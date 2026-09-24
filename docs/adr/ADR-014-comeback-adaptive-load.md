# ADR-014 — Carga adaptativa y modo regreso: volver sin muro

- **Estado**: aceptado (Fases 1, 2 y 3 implementadas 2026-09-20)
- **Contexto**: continúa ADR-009 (D3 sesión, D4 reparto) y ADR-008 (pausa)
- **Decide**: Eddie (alcance y orden de fases), análisis e implementación Claude

## Contexto

Eddie: *"hay días que me voy atrasando y se van haciendo 100 palabras o más…
a pesar de que hay estudio de 10, 20 y 30 min sigue sin adaptarse… quiero que
cuando se me pasen 2 semanas sin estudiar y regrese, continúe donde me quedé…
muchas veces meten palabras nuevas o más reviews y termino no aprendiendo nada."*

### Lo que se midió antes de diseñar (`data/english.db`, 2026-09-20)

| Hallazgo | Dato |
|---|---|
| El reparto de ADR-009 D4 **nunca corrió** | `backlog_spreads`: 0 filas en un mes |
| Por qué: la capacidad era ficticia | ritmo mediano 5 s/card → "20 min" = **240 cards**; nunca había excedente |
| …y sólo disparaba en `session.end` | casi ninguna sentada se cierra a mano: caducan al día siguiente o las pisa la siguiente |
| El tiempo no era el límite | 7-sep: 109 cards en 11 min de reloj, 38 Again |
| Las nuevas entraban sin mirar nada | 19-sep, tras 9 días fuera: plan = **10 nuevas + 100 repasos** |
| La cola abría con lo más olvidado | `ORDER BY fsrs_due`; 19-sep: 6 cards, 5 Again, sentada de 12 s |
| El mazo maduro está sano | recall 92–98% con estabilidad ≥ 2 d |
| Lo joven no se aprende | recall 71% con estabilidad < 2 d; **45%** en pasos `learn`; 44% de todos los repasos son `learn`/`relearn` |
| Cadencia real | 13 días estudiados de 30: cada 2–3 días, no diario |
| La R de FSRS está calibrada para él | predicho < 50% → acertó 39% (n=23); 80–90% → 91% (n=181) |

Conclusión: no era un problema de FSRS ni de disciplina. Eran tres piezas que
no medían lo que decían medir (capacidad), no corrían (reparto) o no miraban
(nuevas), más un orden de cola que convertía cada regreso en una racha de
fallos.

## Decisiones

### D1 — El presupuesto de una sentada es en cards

`session.card_budget`: lo que dé el reloj, **nunca más de 2.5 cards por
minuto** → 25 / 50 / 75 para 10 / 20 / 30 min. `backlog.capacity` usa lo mismo.
Lo que agobia es el número de cards y de fallos, no los segundos.

El ritmo (`pace`) sigue siendo la mediana; con el tope deja de ser quien manda.

### D2 — El día se ordena al sentarse, no al cerrar

`session.start` llama a `backlog.spread` antes de planear. `session.end` lo
sigue llamando (es idempotente: tras ordenar, no queda excedente). Depender de
un cierre explícito que casi nunca ocurre dejó el mecanismo muerto un mes.

### D3 — Compuerta de palabras nuevas (`app/gate.py`)

`new_per_day` pasa de cifra a **techo**. Cuántas entran hoy, en orden:

1. **Palabras volviendo** (D4) → 0. Ellas son las nuevas.
2. **Hueco** → en modo tiempo, `capacidad − vencidas`; si no queda, 0.
3. **Escalera** → ≥ 8 cards en LEARNING/RELEARNING → 0.
4. **Recall de cards jóvenes** (repasos `review` con estabilidad < 7 d, 14
   días, n ≥ 20): ≥ 85% → techo · ≥ 80% → 5 · ≥ 70% → 3 · menos → 0.
   Los pasos de aprendizaje no cuentan: fallar al minuto es parte de aprender.

Sin muestra **no frena**: la compuerta sólo actúa con evidencia. Siempre
devuelve el porqué (`plan.short`), porque recortar callado ya fue un bug
("pedías 6 y te daba 5"). Se apaga con el ajuste `new_gate: off`.

Aplica también en modo manual: el problema es del sistema, no del modo.

### D4 — Triage por recuperabilidad; las perdidas vuelven a goteo

Sustituye la regla 1 de ADR-009 D4 ("se quedan hoy las más atrasadas").

- **Orden**: recuperabilidad descendente, tanto para decidir qué se queda hoy
  como para servir la cola. Con tope diario de repasos es el orden que mejor
  conserva memoria por card contestada, y *due date ascending* — el que había —
  de los peores (simulaciones de los autores de FSRS; ver Referencias). R sale
  de `Scheduler.get_card_retrievability` con la card real. En la cola, como R
  es monótona en `tiempo/estabilidad`, se ordena por ese cociente en SQL.
- **Perdidas** (`R < 0.50`, umbral sacado de su calibración): se marcan con
  `words.comeback_on` y vuelven de **3 en 3 por día**, fuera de la competencia
  por el cupo. Dentro de la sentada se intercalan tras 5 cards y una cada 4,
  nunca de entrada. La card viaja con `comeback: true` para que la UI la
  presente como reencuentro.
- **El estado FSRS no se toca.** No se reinicia nada ni se inventan repasos:
  al contestarla, FSRS registra el lapso o el acierto tardío tal cual fue (un
  acierto tardío sube MÁS la estabilidad). Lo único que el triage cambia es
  *cuándo* llega cada card. `comeback_on` se borra al contestar.
- El resto del excedente se reparte como antes (primer día con hueco contando
  lo ya agendado, parejo si no cabe en 14 días), en orden de R.

Esto es el "continuar donde me quedé": durante la semana de regreso no entran
palabras nuevas; las "nuevas" son las que se cayeron.

## Lo que esto cuesta

- Repartir **retrasa** repasos; sigue midiéndose en `days_late` y en Stats.
- Con R descendente, lo que se empuja es lo de R media-baja, que sigue
  decayendo mientras espera. Es el trade-off que las simulaciones favorecen,
  pero es un trade-off: si el rezago es crónico, la salida es sentarse más o
  meter menos nuevas — la compuerta ya empuja a lo segundo.
- La sentada termina con lo más difícil. El freno (D5) lo acota.

## Verificado

Sobre una copia de la base real (2026-09-20): 98 vencidas → **50 hoy**, 48
agendadas en 3 días, 11 palabras volviendo (3 hoy), 0 nuevas con su razón a la
vista; las primeras cards servidas tienen R = 0.90. `tests/test_comeback.py`
(24 tests) + suite completa en verde.

## Fase 3

### D5 — Freno por fallos

Si tras **15 repasos** de cards vencidas el Again pasa del **35%**, la sentada
deja de servir vencidas y nuevas (`session.limits` → 0/0), termina la escalera
y cierra. Como la cola va en R descendente, cuando los fallos se disparan lo
que queda por delante es peor todavía. Sólo cuentan repasos `review`: fallar
un paso de aprendizaje es parte de aprender. Es consejo, no candado: "Keep
going anyway" lo suelta para esa sentada (`POST /api/session/keep-going`), y
el ajuste `fail_brake: off` lo apaga.

### D6 — Tercer Again del día: la palabra descansa

Hubo cards con 9 repeticiones en una sentada. Al tercer Again del día sobre la
misma palabra, `fsrs_due` pasa al inicio del siguiente día de estudio; la card
FSRS queda como FSRS la dejó. No se suspende ni se esconde (decisión previa de
`model.stuck_words`): vuelve mañana y, mientras, entra al material generado.

Lo de "leeches → contexto" **ya existía** (`model.stuck_words` alimenta todos
los generadores por dificultad FSRS ≥ 9.5). No se duplicó; se añadió que las
palabras que vuelven también entran al material (`COMEBACK_SHARE` = 25%).

### D7 — Nuevas: primero las que ya vio leyendo

Al terminar una lectura, `srs.mark_seen` anota (`words.seen_in_text`) qué
palabras todavía NEW aparecen en ella, y la cola de nuevas las sirve antes. La
primera vez recorre todas las lecturas terminadas. La señal hoy es fina (5
lecturas terminadas) y crece con el uso.

### D8 — "Study more"

`backlog.pull_forward` (`POST /api/backlog/pull`) trae a hoy las próximas 20
cards agendadas (máx. 50, horizonte 14 días, sin tocar el goteo de las que
vuelven). El reparto protege del muro; esto es la puerta de vuelta para el día
que sobran ganas. El botón sólo aparece si no queda nada de hoy y el freno no
saltó.

### Medición

`review_history.comeback` marca los reencuentros; `backlog.comeback_recall`
(en `/api/backlog`) da su recall con muestra mínima de 20.

Verificado en navegador contra una copia de la base (API y vite temporales):
plan, etiqueta de reencuentro, freno a los 15 repasos con 40% de Again, "Keep
going anyway", pantalla final y "Study 20 more". 42 tests en
`tests/test_comeback.py`; suite completa en verde.

## Pendiente

- El estimado de minutos del plan usa la mediana (5 s/card) y dice "50 reviews
  ≈ 4.2 min" junto al botón de 20 min. Es honesto pero choca. La causa de fondo
  es pedagógica: a 5 s la card no hay tiempo de decir el ejemplo en voz alta.
- Llevar `gate` / `triage` a la pantalla Today.
- Revisar el umbral `LOST_BELOW` y los del freno cuando `comeback_recall`
  tenga muestra.

## Referencias

- Expertium / J. Ye, simulaciones de orden de repaso con rezago:
  <https://forums.ankiweb.net/t/ordering-request-reverse-relative-overdueness/50051/28>
  · <https://forums.ankiweb.net/t/improving-sort-orders/50081>
