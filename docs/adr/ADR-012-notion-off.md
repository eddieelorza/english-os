# ADR-012 — Apagar Notion: rescatar el contenido antes de cortar

- **Estado**: aceptado y **ejecutado el 2026-08-21**
- **Contexto**: cierra el último módulo del pipeline legacy, tras ADR-011 (Anki)
- **Decide**: Eddie ("dale con apagar Notion"), implementación Claude

## Contexto

Tras congelar Anki quedaba Notion como espejo. La expectativa era repetir el
mismo procedimiento: medir, comprobar, cortar.

### Lo que apareció al medir

Contando páginas reales contra la base de la app:

| | Notion | App |
|---|---|---|
| VOCAB | 878 | 3,103 |
| WRITING | 77 | 77 |
| READING | 79 | 86 |
| ERRORS | 16 | 35 |
| DAILY PLAN | 17 | 18 |

Los números decían "la app tiene más de todo, corta tranquilo". **Los números
mentían.** Mirando el contenido y no el conteo:

- Los **77 writings** de la app tenían el cuerpo **vacío**. Cero correcciones.
- **79 de 86 readings**, también vacíos.

`importers/notion.py` solo leía **propiedades** (título, fecha, checkboxes);
nunca llamó a `get_block_children`. Las filas eran cascarones: el inglés que
Eddie escribió, las correcciones de la routine y las historias generadas
existían únicamente dentro de Notion.

**Apagar Notion en ese momento habría dejado meses de trabajo inalcanzables, y
nadie se habría enterado hasta ir a buscarlo.** El cut-over se detuvo ahí.

## Decisiones

### D1 — Rescatar primero, cortar después

`app/importers/notion_content.py` baja los bloques de cada página y guarda:

- **la página entera** como texto en `texts.body`
- la sección de corrección aparte en `texts.correction`

Se guarda todo, no solo lo que hoy parece valioso: al archivar no es momento
de decidir qué merece sobrevivir. Idempotente — solo toca filas con el cuerpo
vacío salvo `--refresh`.

Resultado real: **155 páginas rescatadas, 479 KB de contenido, 4 correcciones
extraídas, 0 fallos.** Después, ninguna página con cuerpo vacío.

### D2 — La comprobación previa mira contenido, no conteos

`notion_preflight()` bloquea el apagado mientras exista **una sola** página con
`body` vacío o en blanco. Es la lección de este ADR: contar filas no dice si
hay algo dentro de ellas.

### D3 — Un solo cerrojo para las seis rutas de escritura

Seis scripts escriben en Notion (`anki_notion_sync`, `daily_plan_update`,
`sync_used_words`, `reset_used_today`, `backfill_meanings`, y el propio
cliente). En vez de parchear seis, la guarda vive en
`NotionClient._request()`: cualquier POST/PATCH/PUT/DELETE levanta `NotionOff`.

**Las lecturas siguen funcionando a propósito.** Apagar Notion significa dejar
de alimentarlo, no perder el acceso al archivo. La query de base de datos usa
POST pero es lectura, y está exceptuada.

`importers/notion.py` también se detiene: aquí el riesgo no es pisar
scheduling sino **resucitar filas** — Notion quedó con 878 palabras contra
3,103 y 16 errores contra 35, así que reimportar solo puede desordenar.

### D4 — Notion no se toca

Las páginas quedan intactas y legibles. Reversible con
`scripts/notion_off.py on`.

## Consecuencias

- **El pipeline legacy queda apagado entero.** Anki congelado (ADR-011),
  Notion apagado. La app es el sistema, no un experimento paralelo.
- `CLAUDE.md` tuvo que reescribirse: su diccionario de frases-comando mandaba
  escribir correcciones en páginas de Notion. Una sesión futura habría chocado
  contra `NotionOff` intentando ayudar.
- El archivo de Notion sigue consultable desde Notion mismo, y su contenido
  vive ya en `data/english.db` y en el vault de Obsidian.

## Lo que este ADR enseña

Los conteos coincidían y aun así el corte habría destruido datos. La
comprobación útil no fue "¿cuántas filas hay a cada lado?" sino "¿qué hay
**dentro** de las filas?". Cuando un cut-over parece trivial porque los
números cuadran, ese es el momento de mirar el contenido.
