# ADR-015 — Carga según el ritmo real, IA híbrida y señales de lo que sí hace

- **Estado**: implementado y probado en aislamiento (2026-09-20). **No activado**:
  ver "Activación". Sin commit.
- **Contexto**: continúa ADR-014 (que sigue vigente y no se deshace)
- **Decide**: Eddie; análisis e implementación Claude

## Por qué ADR-014 no bastaba

Eddie: *"no estudio todos los días… termino viendo tantas palabras que no
consigo aprenderlas… los botones de 10/20/30 no resuelven la sobrecarga"*.
Sus cinco hallazgos, comprobados en el código y en `data/english.db` (sólo
lectura, 2026-09-20):

| # | Hallazgo | Comprobación |
|---|---|---|
| 1 | El presupuesto sigue siendo 25/50/75 | Cierto. `MAX_CARDS_PER_MINUTE = 2.5` es una constante mía, no una medida suya. |
| 2 | La escalera sigue tras agotar el presupuesto | Cierto y por diseño (ADR-009: "nunca cortar learning"). Medido: el Again sube con la posición — 28% en las respuestas 1-20, 36% en 41-60, 57% pasada la 80 — porque la cola de la sentada son repeticiones. Sus días: mediana 52-76 respuestas, 1.55 por card. |
| 3 | El reparto ignora su frecuencia | Cierto. `_placement` llenaba día 1, 2, 3… Estudia 11 de 28 días (2.8/semana): al volver a los 3 días le esperaban 3 sentadas apiladas. |
| 4 | El freno excluye fallos de aprendizaje | Cierto. Sólo contaba `review_kind='review'`; su problema está en `learn` (45% de acierto). Y el 35% era un número mío. |
| 5 | Limitar la sesión no basta si siguen entrando nuevas | Cierto. La compuerta miraba recall y hueco, no el tamaño del grupo: 58 palabras sin consolidar; en 14 días entraron 30 y se asentaron 28. |

## Principio

**No se mide "capacidad": no se puede.** Se mide lo que consta en
`review_history` y se separa de lo que es política. Las constantes de política
viven juntas al inicio de `app/load.py` y ninguna se muestra en pantalla como
si fuera una medición suya.

| Medido (suyo) | Política (decisión) |
|---|---|
| días estudiados / observados, días fuera | ventana de 28 días; mínimo 14 observados y 4 estudiados para afirmar un ritmo |
| respuestas por día de estudio (mediana) | horizonte de 14 días para "estar al día" |
| respuestas por card con sus repeticiones | "Less today" = la mitad |
| coste de una card fallada (respuestas extra) | "consolidada" = estabilidad ≥ 7 días |
| entradas y salidas del grupo en 14 días | mínimo de 15 respuestas para que el freno opine |
| su cuartil alto de fallo por sentada | |

## Decisiones

### D1 — La propuesta: conservación, no un dial
`load.proposal`: (vencidas vivas + lo que vence en 14 días) ÷ (sentadas que
cabe esperar a su ritmo) × (respuestas por card) = respuestas por sentada.
Techo: lo que suele hacer en un día (mediana). Si el techo recorta, **lo dice**
("catching up will take longer than 14 days"). Con sus datos reales: ~25 cards
≈ 39 respuestas, frente a su mediana histórica de 76.

Sin historia suficiente no propone nada: cae al plan por tiempo y dice por qué.

### D2 — El límite es de respuestas, repeticiones incluidas
`study_sessions.budget`. `session._budget_limits`: cada respuesta cuenta. Antes
de agotarlo se deja de servir material nuevo y se **reserva** lo que cuesta
terminar la escalera abierta (coste medido). Agotado, tampoco la escalera.
Lo que quede a medias **no se esconde ni se reinicia**: sigue vencido con su
estado FSRS real y abre la siguiente sentada.

### D3 — El reparto sigue su ritmo
`backlog._placement(rate)`: lo agendado hasta el día *d* no pasa de
`cap × ritmo × d`. Con 10 cards/sentada y ritmo 0.4, a los 3 días esperan ≤12
cards, no 30. El reparto usa las cards que **caben en el presupuesto**, no las
"necesarias": si no, cada día quedaba un resto vencido.

### D4 — El grupo: una entra por cada una que se asienta
`load.new_allowed`: `max(asentadas − entradas, techo − tamaño)`, acotado a
`[0, techo]`. El techo es su preferencia (`new_per_day`). Un grupo vacío se
puede rellenar; uno que crece no admite más. Sólo en modo auto.

### D5 — El freno ve los fallos de aprendizaje y usa su línea base
En modo auto cuenta todo menos la primera vista de una nueva, y el listón es
su cuartil alto de fallo por día (hoy 0.37, medido sobre 11 días). Sin 8 días
de historia: 0.35 de ADR-014, marcado como no medido.

### D6 — El día, no la sentada
`settings.load_day` (caduca con el día de estudio): presupuesto fijado al
sentarse por primera vez, `less`, `extra`. "Stop here" cierra cuando quiera; al
volver, el plan es **lo que quedaba**. "Less today" y "Study more" viven ahí y
nunca tocan las preferencias guardadas.

### D7 — IA híbrida (`AI_ROUTE=on`)
Medido en el M5/16 GB: **~18 tokens/s** en `llama3.1:8b` y `qwen2.5:7b`. Una
respuesta corta, ~2 s en caliente; una lectura (~900 tokens) ~50 s; un podcast
~160 s. Ninguna opción de Ollama lo cambia, y **cambiar `num_ctx` entre
llamadas recarga el modelo (3.6-5.5 s)**: un contexto y un modelo, siempre.

El corte es por qué es el texto:
- **personal** (lo que él escribió o dijo): siempre local. Ya es rápido y no
  sale del Mac.
- **generate** (material escrito para él): nube gratuita primero, local de
  respaldo. Cuota agotada o sin red = más lento, nunca roto.

De pago sólo si él lo pone en la cadena **y** fija `AI_CLOUD_BUDGET_USD` **y**
los precios por token. Por defecto gasta **0**. Cada llamada se registra con
su latencia en `logs/ai_calls.jsonl`.

Riesgo corregido de paso: con `AI_PROVIDER=auto`, añadir una clave de
Anthropic mandaba **todo** a `claude-opus-5`. Con `AI_ROUTE=on` ya no.

### D8 — Señales de lo que sí hace (`app/learner.py`, `GET /api/learner`)
El único indicador de éxito (errores/100 palabras) pide ≥150 palabras por
ventana; produjo 250 en 28 días. El sistema medía lo que hace poco e ignoraba
lo que hace mucho. Ahora junta comprensión lectora, acierto en practice,
retención de lo asentado y palabras asentadas, cada una con su muestra (n<5 →
sin número). La meta sólo aparece si él la declara.

### D9 — Carga de pantallas
Regla verificada (ui-ux-pro-max, *Content Jumping* / *Loading Indicators*):
reservar el espacio de lo que llega, no parpadear en respuestas casi
instantáneas, `aria-busy`. `RowsSkeleton` (hairlines con la altura de las filas
reales, espera 140 ms), caché en memoria entre navegaciones
(`peekCache`/`primeCache`), Review ya no pinta el setup antes de saber si hay
sentada abierta, y la página que llega entra deslizándose (sin animación de
salida: no se hace esperar a nadie). Para transición de rutas y caché la skill
no devolvió coincidencia verificada: es criterio general, no una cita.

## Compromisos

- **Aplazar no es aprender.** Una carga menor con rezago grande significa
  repasos más tardíos y más palabras que pasan a "volviendo". Se ve en
  `days_late`, en `backlog.comeback_recall` y en la propia explicación.
- **Cortar la escalera** deja palabras falladas sin repetir hoy; mañana
  llegan con R baja. A cambio la sentada termina cuando dijo.
- **El techo es su hábito, no su capacidad.** Si su hábito era excesivo, el
  techo también lo es; lo que de verdad reduce la carga es la cuenta de D1.
- **El grupo** puede dejarlo semanas sin palabras nuevas si no consolida. Es
  deliberado; se apaga con `new_gate: off`.
- **Nube gratuita**: Google puede usar los datos del nivel gratuito para
  mejorar sus modelos. Por eso sólo viaja material generado, nunca su texto.

## Pruebas

`tests/test_load.py` (26), `tests/test_ai_router.py` (14),
`tests/test_learner.py` (5) — historiales ficticios en memoria: estudio
irregular, regreso a 7 y 14 días, 160 acumuladas, fallos repetidos, "Less
today", recarga y continuación en fichero temporal, historia insuficiente.
Suite: 447 en verde. Recorrido por API y navegador contra una base ficticia en
puertos aislados (8772/5175), con lock y log propios e IA a un puerto muerto.

## Activación (separada, la hace Eddie)

1. `npm run build --prefix frontend` y reiniciar
   (`launchctl kickstart -k gui/$UID/com.eddieelorza.englishos`).
2. En Review, "propose it for me". Volver atrás es elegir "choose by time".
3. IA híbrida, opcional: en `.env`, `AI_ROUTE=on` y `GEMINI_API_KEY=…`
   (verificar `GEMINI_MODEL` y la cuota gratuita vigente).

Hasta el paso 2 nada cambia: modo `time` por defecto, `AI_ROUTE` apagado.

## Pendiente

- El proveedor Gemini está probado con un transporte falso, **no contra el
  servicio real** (no hay clave).
- `learner.context()` existe pero **no está inyectado** en los prompts:
  cambiar prompts sin medir la calidad del resultado no es una mejora probada.
- Pre-generar el material al abrir la app (hoy sólo al cerrar la sentada) es
  lo que más quitaría esperas de 16-70 s en Practice/Writing; es una decisión
  de producto (ADR-011) y no se tocó.
- Streaming en conversación; skeletons con forma en Stats, Vocabulary y Reader.
- Llevar `/api/learner` a una pantalla.
