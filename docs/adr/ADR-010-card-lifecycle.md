# ADR-010 — Ciclo de vida de la tarjeta: estados, log completo y día de estudio

- **Estado**: aceptado (M17a implementado 2026-08-21)
- **Contexto**: Fase 4, continúa ADR-009
- **Decide**: Eddie (fuzz, pasos, alcance), implementación Claude

## Contexto

Eddie pidió reproducir el comportamiento de scheduling de Anki: learning
steps, Again/Hard/Good/Easy, graduación, relearning, cola diaria, historial
completo y FSRS para los intervalos largos.

### Lo que se verificó antes de diseñar

Ejecutando `fsrs` 6.3.2 (la librería que la app ya usaba), con pasos 1m/10m/1d:

| Momento | Again | Hard | Good | Easy |
|---|---|---|---|---|
| Tarjeta nueva | 1m · step 0 | 6m · step 0 | 10m · step 1 | 8d · **gradúa a REVIEW** |
| Con Good | step 0→1→2 → gradúa → 6d → 28d → 106d (calculados) |

Y el lapse:

    REVIEW      stability 34.13  difficulty 2.10
      ↓ Again
    RELEARNING  step 0  +10m  stability 2.55  difficulty 7.39

**Conclusión: la máquina de estados ya existía y ya corría.** Es la librería.
No se construyó un scheduler casero ni se cambió de librería. Lo que faltaba
era exponerla, configurarla, poder previsualizarla y registrarla entera.

## Decisiones

### D1 — Sin fuzz (Eddie)

FSRS trae `enable_fuzzing=True` por defecto: reparte los vencimientos al azar
para que no se apelmacen. Medido, seis llamadas idénticas sobre la misma
tarjeta nueva con `Easy`:

    con fuzz:  [9, 9, 7, 11, 8, 9] días
    sin fuzz:  [8, 8, 8, 8, 8, 8] días

En intervalos largos la dispersión llega a ±25 días. Como la UI va a prometer
el intervalo encima de cada botón (requisito de Eddie), el fuzz haría mentir a
esa promesa. Se apaga.

**Coste asumido**: las tarjetas contestadas el mismo día tienden a volver
juntas. Lo compensa el reparto del rezago de ADR-009 D4.

**Efecto lateral bueno**: el sembrado desde Anki ya usaba `enable_fuzzing=False`
y las respuestas en vivo usaban fuzz. Ahora hay **un solo scheduler**
(`srs._scheduler()`); sembrar y contestar dejan de discrepar.

### D2 — Pasos 1m/10m por defecto, configurables (Eddie, M17b implementado)

Es el default de Anki y **es lo que sus tarjetas ya usan**, así que nada se
reprograma.

`app/deck.py` guarda los pasos como texto legible (`"1m,10m"`) en `settings` y
los parsea a `timedelta`. Se **valida al guardar**, no al usar: unos pasos rotos
dejarían el mazo sin poder programar nada y el fallo aparecería al contestar una
tarjeta, no al configurarla. También se exponen `desired_retention` (acotada
entre 0.7 y 0.98) y `enable_fuzzing`.

La **hora de corte no se edita desde la app**: `db.study_day()` se llama desde
sitios que no tienen conexión abierta, así que leerla de la base obligaría a un
caché global con su propia invalidación. Vive en `.env`
(`STUDY_DAY_ROLLOVER_HOUR`) y la config sólo la reporta, con
`rollover_hour_editable: false` para que la UI no finja lo contrario.

### D8 — `preview(word_id)`: los cuatro intervalos (M17b)

La pieza que de verdad no existía. Pasa una **copia** de la card por el
scheduler una vez por rating y devuelve intervalo, vencimiento, estado
resultante y si eso gradúa la tarjeta.

- Es **exacto**, no aproximado, porque el fuzz está apagado. Un test compara lo
  prometido con lo que hace `answer()` para los cuatro ratings: si el botón
  dice 10m, son 10m.
- Si alguien enciende el fuzz, `exact: false` lo advierte en vez de seguir
  prometiendo.
- Viaja **dentro de la respuesta de la cola**: la UI necesita los cuatro
  números junto a la card y una segunda petición sólo añadiría parpadeo.
- **No puede tumbar la cola.** Un `fsrs_card` corrupto haría reventar la
  pantalla entera de Review; estudiar importa más que ver los intervalos, así
  que el preview degrada a `null` y reporta `preview_error` en el payload —
  visible, no tragado en silencio.

Nota de comportamiento real, no un bug: con una tarjeta de estabilidad muy baja
(recién recuperada de un lapse), Good y Easy pueden mostrar **el mismo** valor
— ambos 1d — porque FSRS no puede justificar más. Anki hace lo mismo.

### D3 — NEW no es un estado de FSRS

La librería sólo conoce Learning(1), Review(2), Relearning(3). "Nueva" es la
**ausencia de card** (`fsrs_card IS NULL`). El mapeo queda explícito en
`srs.STATE_NAMES` y `card_state` guarda `'NEW'` para esas filas.

`words.status` (NEW/LEARNING/FAMILIAR/MASTERED) es **otra cosa**: el estado de
vocabulario estilo LingQ que consumen Reader y Stats. Se mantienen separados;
confundirlos fue una tentación real al implementar.

### D4 — Espejo consultable, con el JSON como fuente de verdad

`state`, `step`, `stability` y `difficulty` llevaban dentro de `fsrs_card`
desde M4, pero no se puede hacer `WHERE` ni `GROUP BY` dentro de un blob y la
cola diaria necesita separar LEARNING de REVIEW en SQL. Se promueven a
columnas de `words` — **espejo, no verdad**: se reescriben en cada `answer` y
`backfill()` las rellena desde el JSON existente sin inventar nada.

### D5 — ReviewLog completo, nunca se sobreescribe

`ReviewLog` de FSRS sólo trae `card_id`, `rating`, `review_datetime` y
`review_duration`: **la estabilidad y la dificultad previas se pierden si no
se capturan alrededor de la llamada**. `answer()` toma el "antes" antes de
tocar nada y escribe una fila con estado, paso, estabilidad y dificultad antes
y después, más `previous_due` y `elapsed_days`.

Las 1,050 filas importadas de Anki quedan con esas columnas en `NULL`. Es
honesto: esa información no existía cuando se importaron.

### D6 — Día de estudio con hora de corte, no fecha de calendario

`now_iso()[:10]` era "hoy" en 23 sitios. Estudiar a las 00:30 abría un día
nuevo: rompía la racha, reiniciaba el cupo de palabras nuevas y cerraba la
sentada en marcha. Se introduce `db.study_day()` con corte a las **4:00**
(como Anki), configurable con `STUDY_DAY_ROLLOVER_HOUR`.

El concepto es **uno solo para toda la app**: el archivo por día del material
usa el mismo corte que el scheduling, así que una lectura generada a la 01:00
se archiva con la noche a la que pertenece.

### D7 — NO se migra el historial a UTC (revisión de la propuesta inicial)

En el diseño propuse "almacenar siempre UTC". **Se descarta tras mirarlo de
cerca.** Conviven dos marcos:

- `now_iso()` — reloj de pared local, ingenuo. Lo llevan las 1,088 filas de
  historial y todo lo archivado por día.
- `now_utc()` — aware en UTC. Es el marco de FSRS (`fsrs_due` trae offset).

Cada comparación del código vive dentro de **un solo** marco, así que no hay
bug en producción; el riesgo es que código futuro los mezcle por accidente.
Reescribir 1,088 filas para un usuario en una sola zona horaria es un riesgo
real a cambio de un beneficio teórico. Se documenta la frontera y se deja el
helper `srs._utc()` que normaliza ambos casos.

### D9 — La cola, separada por grupo (M17c)

`study_queue()` devuelve NEW / LEARNING / REVIEW por separado, con cuentas y
una **muestra acotada** de ids (25 por grupo). No devuelve la lista entera a
propósito: con miles de palabras nuevas serían megabytes que nadie mira, y el
contador ya dice la verdad.

Separarlos importa porque no se comportan igual: una card de aprendizaje
**reaparece en la misma sentada**, una de repaso desaparece hasta su fecha.
Un único "quedan N" esconde esa diferencia.

`queue()` y `study_queue()` comparten `_buckets()`: una sola definición de qué
hay disponible, para que la card que se sirve y el contador que se pinta no
puedan discrepar. Las consultas pasan a usar la columna `card_state` en vez de
`json_extract` — para eso se promovió en M17a, y así entra el índice.

**Estrategias de mezcla** (`deck.queue_mix`):

| Modo | Orden |
|---|---|
| `due_first` (default) | vencidas → nuevas → learn-ahead |
| `new_first` | nuevas → vencidas → learn-ahead |
| `mixed` | una nueva cada `spacing` cards, repartidas entre los repasos |

El learn-ahead va **siempre al final**: adelantar una palabra que fallaste
sólo tiene sentido cuando no queda nada más. `mixed` usa la posición dentro de
la sentada; sin sentada abierta se comporta como `due_first`.

### D10 — Los intervalos, encima de los botones (M17c)

El número va **arriba** del botón, como en Anki: es una propiedad de la
elección, no un pie de foto del resultado. Dice cuándo vuelve la card, nunca
cuánto llevas estudiándola. Cuando una respuesta gradúa la tarjeta se dice con
una palabra debajo — es el momento en que deja los minutos atrás.

Verificado en el navegador contra datos reales: el botón prometió `1d` para
`shortly` y al pulsarlo se aplicó `1.000d`.

## Consecuencias

- Se puede consultar el mazo por estado, que es lo que M17c necesita para
  `getStudyQueue()` con contadores separados.
- Se pueden construir estadísticas por palabra (Reviews / Again / Hard / Good
  / Easy, primera vez, última, próxima) — el §14 de la petición de Eddie.
- Trasnochar deja de romper la racha.
- Pendiente en M17b: `deck_config` (pasos, retención, fuzz, corte de día) y
  `preview(word_id)`. Pendiente en M17c: la cola separada y los intervalos
  encima de los botones.
