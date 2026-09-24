# ADR-009 — La sesión de repaso: presupuesto, pasos de aprendizaje y backlog

- **Estado**: aceptado (M16a implementado 2026-08-21)
- **Contexto**: Fase 4, tras ADR-008
- **Decide**: Eddie (las tres preguntas de diseño), implementación Claude

## Contexto

Eddie comparó la pantalla de Review con Anki y encontró tres cosas: las cards
nuevas enseñaban la respuesta sin pedirla, una palabra fallada no volvía "hasta
que quedara clara", y no había forma de decir "hoy tengo 20 minutos" ni "hoy
quiero 6 nuevas y 25 repasos". Todo ello con un requisito de fondo:

> "pero jamás que se haga una cola gigante que me haga sentir que ya se me juntó"

### Qué se verificó antes de decidir

Contra `data/english.db` real (2026-08-21), no de memoria:

- 3,103 palabras; **171 con card FSRS**; 2,226 NEW sin tocar.
- **5 vencidas** ahora mismo. Próximos 7 días: 5, 16, 6, 3, 4, 8, 2.
- Intervalos ya repartidos: 36 palabras a 21–60 días, **57 a 2–6 meses**.
- `Scheduler()` ya trae learning steps de 1 y 10 min, y relearning de 10 min.
- Mediana de 5.0 s/card sobre 1,039 huecos del revlog de Anki.

**Conclusión 1**: la petición "que las dominadas vuelvan en 24 días, en 2 meses"
**ya estaba resuelta** por FSRS. No se construyó nada para eso.

**Conclusión 2**: la cola gigante **todavía no existe**. Se diseña antes de que
aparezca, no en pánico — y la palanca real es el ritmo de palabras nuevas
(cada nueva genera ~8–10 repasos futuros), no el tope de repasos.

**Conclusión 3**: los 5 s/card **no se usan** para calibrar. Vienen del mazo
viejo en Anki, y esta app lleva 27 repasos in-app: no es muestra. Se arranca
conservador y se auto-calibra (M16b).

## Decisiones

### D1 — Frente primero, también en las nuevas

`ReviewPage` revelaba la respuesta cuando `is_new`. Era deliberado ("no puedes
recordar algo que nunca viste") y estaba mal: Anki muestra el frente en las
nuevas también, y entregarla abierta convierte la card en un póster. Ahora
siempre se destapa a petición.

### D2 — La cola deja de esconder las cards en aprendizaje

`queue()` pedía `fsrs_due <= now`. Una palabra marcada *Otra vez* queda para
dentro de 1 minuto, así que **desaparecía**; si era la última, la app decía
"The deck is clear" y expulsaba de la sesión justo con la palabra peor sabida.

Se añade `LEARN_AHEAD_MINUTES = 20` (el *learn-ahead limit* de Anki): cuando no
queda nada más, se muestran las cards en Learning/Relearning antes de su
minuto. Orden de selección:

    vencidas ahora → una palabra nueva del presupuesto → learn-ahead

La nueva va **antes** del learn-ahead a propósito: espacia la palabra fallada
por una card o dos en vez de repetirla al instante, que es el sentido del paso.
Decisión de Eddie: "a los pocos minutos, como Anki".

También se corrige que `due` se contaba con `len(rows)` sobre un `LIMIT 500`:
el contador mentía a partir de 500 vencidas. Ahora es `COUNT(*)`.

**Revisión 2 (M18)**: la ventana fija era el error de fondo, en las dos
direcciones. Con 20 min la sentada se alimentaba sola; con 3 min pasó lo
contrario — una card en el paso de 10 minutos quedaba **invisible** para la
cola, la app decía "nothing to study right now" con trabajo pendiente, y la
palabra reaparecía un rato después. Esperar mirando una pantalla vacía no
enseña nada.

Ahora hay **dos** ventanas:

- **Mientras quede otra cosa** (vencidas o nuevas): 3 min. El reloj manda.
- **Cuando no queda nada**: se abre hasta cubrir la escalera de aprendizaje
  entera (`deck.longest_step_minutes`, 10 min con los pasos por defecto). No
  más: una card graduada a días vista no es learn-ahead, es trabajo de mañana.

La regla se lee sola: *el reloj manda mientras haya alternativa; cuando no la
hay, no hay nada que esperar*. Y la sentada sigue terminando, porque al
graduarse la card sale de la escalera — verificado con un recorrido completo.

**Revisión 3 (M18b)**: abrir la ventana sin suelo la abrió demasiado. Sin nada
más en la cola, una card marcada *Otra vez* con vuelta "en 1 minuto"
reaparecía **a los 2 segundos**: seis respuestas a la misma palabra en 55
segundos, medidas en su propio historial. FSRS puntúa *tiempo transcurrido*,
así que acertar al instante no prueba memoria (apenas suma) y fallar al
instante hunde la estabilidad — `trim` pasó de 0.212 a 0.066 en un minuto, y
con esa estabilidad hasta el botón *Easy* ofrece 1d. El bucle no sólo cansaba:
falsificaba el scheduling y fabricaba palabras atascadas.

El suelo es el **paso más corto del mazo** (`deck.shortest_step_minutes`, 1 min
por defecto): se puede adelantar el paso de 10 minutos, nunca por debajo del de
1. Las cards que esperan no desaparecen de los contadores — viajan como
`cooling` con un `resume_at`, y la pantalla enseña una cuenta atrás que se
reanuda sola en vez de decir "no queda nada". Regla final: *un paso mide tiempo;
si no transcurre, no es un paso.*

**La reparación (M18c)**: arreglado el bucle quedaba el destrozo que dejó.
`app/repair.py` recalcula la card replicando el historial **sin** las
respuestas que llegaron a menos de 60 s de la anterior. No borra historial:
esas respuestas ocurrieron y el registro es cierto; lo que estaba mal era la
lectura que el scheduler hacía de ellas.

Alcance medido antes de tocar nada: **38 respuestas rápidas en 10 palabras**,
30 de ellas el 2026-08-24. Un primer prototipo replicaba *todo* el historial
y "reparaba" 42 palabras — porque Anki repetía cards a los pocos segundos en
sus pasos de aprendizaje, y eso era su funcionamiento normal. El filtro se
ciñe a `source='fsrs'`.

**Y el resultado honesto: casi no cambia nada.** La lista de atascadas pasa de
33 a 32 — sólo sale `trim`. En los cinco días siguientes al bug Eddie repasó
`coal` ocho veces y falló seis, así que su estabilidad de 0.002 no la causó el
bucle: está ganada. El daño quedó superpuesto por repasos reales. La
reparación deja el registro en lo que habría sido, no mejora el estudio — y
las 32 que quedan son dificultad de verdad, no secuela de un fallo.

**Revisión 1 (M16b)**: la ventana arrancó en 20 min, el default de Anki, y era
demasiado ancha. Los pasos de aprendizaje son 1 y 10 min, así que una card que
acababas de **acertar** volvía a los 10 — dentro de la ventana. La sentada se
alimentaba sola: un plan de 9 cards iba por 16 sin terminar. Se baja a **3
min**, que cubre el primer paso con margen. La regla queda legible: *una
palabra que fallaste vuelve; una que acertaste sigue su camino*.

### D3 — Presupuesto por tiempo como control principal (M16b, implementado)

Eliges 10/20/30 min y la app muestra el desglose antes de empezar ("6 nuevas ·
24 repasos ≈ 20 min"). Modo manual por números para "6 y 25" exactos. El plan
nunca promete lo que no hay: recorta contra lo vencido y contra el tope diario.

La calibración se mide de los huecos entre repasos in-app; por debajo de 30
muestras devuelve 10 s/card y **lo dice en pantalla** en vez de fingir
precisión. Los 5 s del revlog de Anki no se usan (mazo distinto, card distinta).

Detalles que costaron un bug cada uno:

- `review_kind` valía `'learn'` tanto para *introducir* una palabra como para
  *repasar* una card en paso de aprendizaje. La sentada contaba lo segundo
  como palabra nueva: un plan de 5+5 cerraba diciendo "10 new · 0 reviewed" y
  gastaba el cupo equivocado. Se separa en `'new'` vs `'learn'`.
- El progreso se cuenta por **id de review**, no por `reviewed_at`: los sellos
  tienen resolución de segundo y un repaso hecho en el mismo segundo en que
  abres la sentada caía dentro de ella.
- Una sentada abierta **se cierra sola al día siguiente**. Si no, levantarte
  sin cerrarla deja el contador arrastrando los repasos de ayer ("38 de 10").
- La columna nueva de `study_sessions` necesitó entrada en `MIGRATIONS`:
  `CREATE TABLE IF NOT EXISTS` no toca una tabla ya creada, así que las bases
  existentes se quedaban sin ella.

### D4 — El backlog se reparte, no se esconde (M16c, implementado)

Cuando lo vencido supera lo que cabe en un día, el excedente **se re-agenda
repartido** en los días siguientes (`app/backlog.py`). Se dispara al cerrar la
sentada — hiciste tu parte, el resto se ordena — y nunca durante una pausa.

Reglas del reparto:

- Se quedan hoy las **más atrasadas**: si algo va a esperar más, que sea lo
  que menos lleva esperando.
- Cada carta va al primer día con hueco **contando lo ya agendado ahí**. Sin
  esto el reparto amontona: repartir 112 cartas de 8 en 8 dejaba 59 en un solo
  día, porque ignoraba las 51 que ya vencían mañana.
- Si el rezago **no cabe** en el horizonte de 14 días al ritmo deseado, los
  días salen más cargados pero **parejos**, y se devuelve `over_capacity` con
  el número real. Apilar el sobrante en el último día construía un muro de 126
  cartas a dos semanas vista — el mismo problema, sólo aplazado.

**Coste asumido y explícito**: repartir *retrasa* repasos, no los elimina. Cada
repaso guarda ahora su `days_late`, y **Stats lo muestra** (M16d): acierto por
tramo de retraso — a tiempo / 1-3 días / 4+ días — cada uno con su muestra, y
un tramo con menos de 20 repasos no afirma porcentaje. Junto al dato va la
causa (cuántas cartas se repartieron en los últimos 30 días), porque un
retraso puede venir del sistema o de una semana sin estudiar y la pantalla no
debe confundir las dos cosas. El precio es medible en vez de supuesto. No se puede prometer a la vez "nunca cola gigante" y "retención
óptima"; Eddie eligió no ver la cola gigante.

### D5 — La palanca real son las palabras nuevas (M16c)

Un tope de repasos no controla la carga futura: cada palabra introducida acaba
consumiendo varios repasos, así que el ritmo de nuevas la fija. `projection()`
lo calcula por conservación — N nuevas/día × R repasos/palabra = N×R repasos
diarios en régimen — con **R medido de su propio historial** (hoy 6.3, cota
inferior porque sus palabras son jóvenes), no con una constante inventada.

El aviso vive junto al control que fija las nuevas, no en una pantalla de
ajustes que nadie abre. Y en modo manual el número de "New words" es también
el cupo **del día**: pedir 6 y recibir 5 en silencio (por un `new_per_day`
aparte) hacía mentir a la propia pantalla.

### D6 — Las palabras atascadas son las que no se parecen al español (M18d)

Reparado el bug quedaban 32 palabras atascadas, y resultó no ser un problema
de scheduling. Medido sobre su propio mazo:

| grupo | parecido ortográfico inglés↔español | % cognados |
|---|---|---|
| atascadas | 0.28 | **12 %** |
| dominadas (≥30 d) | 0.61 | **66 %** |

Y en todas las palabras con card: los cognados tienen **intervalo mediano de
32 días y dificultad 3.1**; los no-cognados, **16 días y 5.8**. `province`,
`archaeology`, `corridor`, `glory` se leen solas; `coal`, `sew`, `shed`,
`needle` no regalan nada. Ninguna otra variable separaba los grupos: mismo
mazo (`Essential English Words::3.Book`, intervalo medio 33 d), mismo número
de repasos, y las 32 ya aparecían en las lecturas generadas — exposición no
les faltaba.

Dos defectos concretos salieron de mirar las tarjetas una por una:

1. **El reverso no enseñaba significado, sólo una palabra en español.**
   `meaning_en` estaba vacío en el **100 %** de las tarjetas. Para un cognado
   da igual; para un no-cognado es memorizar un par sin asidero. Se rellena
   con `app/glossary.py` (ver abajo). La UI ya pintaba ese campo, así que no
   hizo falta tocar la pantalla.
2. **Seis traducciones no correspondían al sentido de su propio ejemplo**:
   `burst` decía "Ráfaga" con *the bomb burst*; `disguise` decía "Ocultar"
   con *the Santa disguise*; y `surge` decía "Sobretensión" —  la acepción
   eléctrica— con *a surge of runners*. Corregidas a mano.

Sobre generar las definiciones con el modelo local: **define bien, inventa
mnemotecnias fatal**. Los ganchos que produjo eran incoherentes ("SHED suena
como 'sed', y tu sed puede aliviar la sed de querer un cobertizo"), así que se
descartaron. Y una definición llegó con caracteres chinos y restos del JSON
mezclados, pasando todas las validaciones que había: por eso `glossary.problem`
rechaza ahora cualquier carácter fuera del inglés. Cuatro definiciones están
escritas a mano, incluida `endure`, donde el modelo se equivocó de significado
("to become stronger or more resilient" — endure es soportar).

**Es una apuesta y se mide igual que la anterior**: si dentro de dos semanas
siguen siendo 32, la definición en inglés no era la palanca.

## Consecuencias

- La sesión ya no termina mientras haya algo sin aprender.
- El contador de la cabecera pasará a hablar de la sesión, no del total
  vencido: ver "200 due" es exactamente la sensación que se quiere evitar.
- Anki sigue siendo el mazo de verdad hasta que Eddie decida el cut-over; nada
  de esto escribe en Anki.
