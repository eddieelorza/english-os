# ADR-011 — Cut-over de Anki: la app pasa a ser la única verdad

- **Estado**: aceptado y **ejecutado el 2026-08-21**
- **Contexto**: cierra el camino abierto en ADR-006 ("Notion y Anki se apagan módulo a módulo")
- **Decide**: Eddie (congelar Anki), implementación Claude

## Contexto

Desde M4 convivían dos sistemas que programaban: Anki era el mazo histórico y
la app leía de él, pero la app también empezó a programar por su cuenta. Iban
divergiendo en silencio.

### Lo que se midió antes de cortar

Cruzando `anki_note_id` entre la base de la app y AnkiConnect en vivo:

| | |
|---|---|
| Estudiadas en **ambos** | 166 |
| Estudiadas **solo en la app** | 5 (las de ese día) |
| Estudiadas **solo en Anki** | **0** |
| Nuevas en ambos | 2,226 |
| En la app sin nota en Anki | 706 |

**Anki no tenía nada que a la app le faltara**, así que cortar no perdía
progreso. Las 706 de más vienen del `.apkg` completo (3,103 notas) frente a la
colección real de Eddie (2,402): no importó todos los libros.

Esto invirtió la expectativa. Se temía tener que reconstruir cards FSRS a
partir del `interval`/`ease` de Anki para miles de palabras; no hizo falta
ninguna.

## Decisiones

### D1 — Anki se congela como archivo (Eddie)

El mazo queda **intacto**. Nadie escribe en él ni lee de él para programar. La
app es la única verdad.

**Coste asumido y dicho**: Anki tiene app de móvil y esto no. Se pierde
estudiar fuera del escritorio. Eddie lo eligió a cambio de dejar de tener dos
sistemas que se contradicen.

No se implementó el empuje app → Anki: mantendría el móvil como lectura, pero
cualquier repaso hecho allí se perdería o crearía conflicto, o sea una fuente
de divergencia nueva para resolver la que acabamos de cerrar.

### D2 — Las guardas, que son el cut-over de verdad

Sin ellas la marca es una etiqueta. Dos sitios pisarían el estado de la app:

1. **`importers/anki.py`** escribe con
   `overwrite=("status", "ease", "interval_days", "lapses", "review_count", …)`.
   No toca el scheduling FSRS, pero **sí `status`**, así que una palabra que la
   app ya avanzó volvería a lo que Anki recuerda. Corrupción silenciosa, del
   tipo que se descubre semanas después. Ahora el importador se detiene y lo
   dice (`{"skipped": "cut-over"}`); `force=True` es la salida de emergencia
   explícita.
2. **`run_all.py session-end`** se retira entero. Abrir Anki para mirar algo ya
   no relanza el pipeline.

### D3 — El disparador se muda al cierre de la sentada

El add-on de Anki lanzaba `session-end`, que pre-generaba el material del día.
Sin Anki, nadie lo lanzaba y el material dejaría de aparecer.

Ahora lo dispara `session.end()`: encola actividades, consejo y —si no existe
ya— la lectura del día, y **sigue sin esperar**. Generar tarda minutos y nadie
va a mirar la tarjeta de cierre mientras tanto.

La guarda contra duplicar vive en `jobs.enqueue_daily()`, compartida por los
dos disparadores: mientras Anki siga instalado podrían coincidir, y dos
lecturas el mismo día es justo lo que CLAUDE.md prohíbe.

Cerrar la sentada **nunca falla por el material**: si la cola revienta, el
error viaja en la respuesta y la sentada se cierra igual.

### D4 — Reversible, y con foto del estado final

`scripts/cutover.py revert` apaga la marca y el pipeline vuelve a leer de Anki
como antes. Se guarda una foto del estado final de Anki (2,402 cards: 166
review, 2,236 nuevas) para poder responder dentro de un año "¿qué había el día
que corté?" sin adivinar.

Antes de cortar hay tres comprobaciones, y `run` no corta si alguna falla:
AnkiConnect responde, **nada estudiado sólo en Anki**, y existe copia de
seguridad.

## Consecuencias

- La app es la única fuente del scheduling. Se acabó la divergencia.
- Anki sigue instalado y utilizable para consultar; simplemente ya no cuenta.
- El add-on puede quedarse: `session-end` se retira solo.
- **Notion sigue como espejo** del pipeline legacy — este ADR cierra Anki, no
  Notion. Ese es el siguiente módulo a apagar.
- Sin móvil. Si algún día pesa, la salida no es resucitar Anki sino hacer la
  app accesible desde el teléfono.


## Apéndice — el vigilante que sobrevivió al corte (2026-08-31)

`anki_watcher.sh`, cargado en `launchd` como `com.english.anki-watcher`,
sondeaba cada 10 s y al cerrar Anki lanzaba `run_all.py morning`. Este ADR
congeló Anki y ADR-012 apagó Notion, pero **nadie lo descargó**: siguió vivo
diez días. El día que Eddie abriera Anki por curiosidad, habría disparado un
pipeline condenado a `NotionOff` y le habría enseñado una alerta de fallo que
no significaba nada.

La causa de fondo es que el corte no lo conocía. Ahora sí:

- `cutover.state()` incluye `anki_watcher_loaded`. Un corte "hecho" con el
  vigilante encendido no está hecho, y durante diez días nada lo dijo.
- `cutover.revert()` lo vuelve a cargar desde
  `scripts/legacy/com.english.anki-watcher.plist`. Un revert que no reactiva
  el disparador del pipeline legacy es media promesa.
