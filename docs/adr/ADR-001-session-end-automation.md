# ADR-001 — Automatización del fin de sesión de Anki

> Estado: **aceptado e implementado** (2026-07-29), con un pivote durante la
> implementación documentado abajo (§ launchd rechazado por TCC).
> Contexto de producto: Vision P2 (dato como subproducto) y criterio de UX de Eddie:
> *"mi única acción diaria debe ser abrir Anki y estudiar"*.

## Contexto

El disparo automático existía pero era frágil:

- El add-on lanzaba `run_all.py morning` fire-and-forget: sin notificación, sin
  registro de éxito/fallo, bajo el Python embebido de Anki, y sin idempotencia
  de sesión (el lockfile evita concurrencia, no re-ejecución).
- El hook `profile_will_close` y `anki_watcher.sh` disparaban el pipeline
  **cuando Anki ya se estaba cerrando/cerrado** — pero el primer paso
  (`anki_notion_sync.py`) necesita AnkiConnect (`localhost:8765`), que muere con
  Anki. Esa ruta fallaba por construcción.

## Decisión

El add-on detecta el fin de sesión (mismos hooks de siempre) y lanza
`run_all.py session-end` como **proceso hijo detachado** (`start_new_session=True`)
vía `/bin/zsh -lc`, de modo que corre bajo el `python3` del usuario, no el de Anki.
Toda la inteligencia vive en el nuevo modo `session-end` de `run_all.py`:

```
Anki (add-on)                              run_all.py session-end (proceso propio)
─────────────                              ────────────────────────────────────────
estudia cards                              1. lock (flock, ya existía)
  └─ reviewer_did_answer_card              2. espera AnkiConnect hasta 60s
     → _had_reviews = True                    └─ down → estado pending + notificación,
vuelve al deck browser                           exit 0 (nada se pierde: rated:1
(o cierra Anki)                                  re-cubre el día en el próximo run)
  └─ Popen detachado ────────────────────► 3. idempotencia: si reviews de hoy ==
     "cd repo && exec python3                 último run ok → sale en <1s
      run_all.py session-end"              4. anki_notion_sync      (existente)
                                           5. writing_session_daily (existente)
                                           6. reading_page_daily    (existente)
                                           7. learner_profile_update (nuevo)
                                           8. plan diario (skip sin ANTHROPIC_API_KEY)
                                           9. guarda estado + notificación macOS
```

### launchd: evaluado, implementado y rechazado (con evidencia)

El diseño original era: add-on escribe un trigger file → LaunchAgent con
`WatchPaths` ejecuta el pipeline. Se implementó y falló en el primer test real:

```
/Library/Developer/CommandLineTools/usr/bin/python3: can't open file 'run_all.py':
[Errno 1] Operation not permitted
```

**Causa**: macOS TCC. `~/Desktop` es carpeta protegida; un proceso de `launchd`
no hereda el permiso de acceso y no recibe prompt — se le deniega en silencio.
La única salida era dar **Full Disk Access a python3**, un grant de seguridad
desproporcionado para este problema. Rechazado.

El proceso hijo de Anki, en cambio, **hereda el grant de Anki** sobre Desktop
(proceso responsable = Anki). Evidencia: el add-on anterior lanzaba el pipeline
exactamente así durante meses (logs de mayo 2026).

### Otras alternativas descartadas

| Alternativa | Veredicto |
|---|---|
| Solo watcher `pgrep` (anki_watcher.sh) | Corre cuando Anki YA cerró → AnkiConnect down → sync imposible. **Deprecado**; no volver a arrancarlo. |
| Leer collection.anki2 (SQLite) directo | DB bloqueada/inconsistente con Anki abierto. Vetado. |
| launchd `StartInterval` (polling) | Mismo problema TCC + latencia/ruido. |

### Idempotencia de sesión

`logs/.session_state.json` guarda `{date, reviews_processed, status, ts}` donde
`reviews_processed` = `getNumCardsReviewedToday` al último run exitoso. Un nuevo
disparo con el mismo contador y status `ok` sale en <1 s sin tocar Notion.
Estudiar más tarde el mismo día (contador sube) re-procesa — deseado; las palabras
ya sincronizadas se saltan por `Synced On = hoy` y el upsert por `Anki Note ID`
garantiza cero duplicados. `--force` ignora el estado.

### Manejo de errores

- **AnkiConnect caído** (cerró Anki al instante) → estado `pending` + notificación;
  el próximo fin de sesión o el comando manual completan el día. Exit 0.
- **Notion 429/5xx** → `NotionClient` reintenta con backoff; fallo persistente →
  estado `failed`, notificación con el log a revisar, exit ≠ 0.
- **Fallo a mitad de pipeline** → scripts idempotentes por día; re-ejecutar es seguro.
- Anki nunca se ve afectado: proceso separado, tooltip como única UI dentro de Anki.

## Archivos

| Archivo | Cambio |
|---|---|
| `anki_addon/__init__.py` | Reescrito: spawn detachado de `session-end` vía zsh login shell. Ya no lee `.env` (cero secretos en el proceso de Anki). |
| `run_all.py` | Nuevo modo `session-end` (+ `--force`): espera AnkiConnect, idempotencia por estado, pasos existentes + learner profile + hook de plan, notificación macOS. |
| `scripts/learner_profile_update.py` | Nuevo: métricas de sesión desde AnkiConnect (`cards_reviewed`, `introduced`, `again`, `again_rate` por día) → `data/learner_profile.json`. Semilla del Learner Profile. |
| `.gitignore` | + `data/`, `logs/.session_state.json`. |
| `anki_watcher.sh` | **Deprecado** (su caso de uso murió con este ADR). No se borra aquí. |

## Revisión 2026-07-30 — control de disparo (anti-gasto accidental)

El modelo original disparaba al volver al deck browser con ≥1 review. En uso real
eso resultó demasiado sensible: contestar una card por accidente corría el
pipeline completo, volver al menú de mazos a mitad de sesión lo corría otra vez,
y una segunda tanda de estudio en el mismo día **regeneraba el material** encima
del que Eddie ya estaba trabajando (el `session_id` incluía el contador de
reviews, así que reseteaba `AI Status` a Pending).

Tres compuertas, de la más barata a la más cara:

| # | Compuerta | Dónde | Efecto |
|---|---|---|---|
| 1 | **Debounce de inactividad**: se dispara tras 2 min sin contestar cards (o al cerrar el perfil), ya no al renderizar el deck browser | `anki_addon` (QTimer, se reinicia con cada card) | Estudiar en tandas cortas no dispara nada de más |
| 2 | **Umbral de sesión real**: `MIN_SESSION_REVIEWS` (default 10) reviews acumuladas hoy | `run_all.session_end` | 1-2 cards por accidente → cero escrituras en Notion, cero cuota |
| 3 | **Material una vez al día**: `routine_fired_on` en el estado + `AI Session` = fecha (ya no fecha+contador) | `run_all` + `daily_plan_update` | Una segunda sesión sincroniza palabras (barato, local) pero NO vuelve a pedir material ni pisa lo generado |

`--force` salta las tres. Verificado: 5 reviews → no procesa; material ya
generado → `fire_routine` 0 llamadas; primera sesión del día → 1 llamada.

### Snapshot de sesión — el fallo real del 2026-07-30

Primer uso en producción: Eddie estudió 56 cards y **cerró Anki de inmediato**.
El pipeline arrancó, alcanzó a leer el contador de reviews (AnkiConnect aún
respiraba) y murió 2 s después en `anki_notion_sync`:

```
09:42:15  ═══ Session-end pipeline ═══
09:42:16  ▶  anki_notion_sync.py
09:42:18  ✗  anki_notion_sync.py terminó con código 1
```

El diseño solo contemplaba "AnkiConnect ya está caído al empezar", no "se cae a
mitad". Y esperar a que Anki cierre para disparar es intrínsecamente racy.

**Solución**: el add-on congela la sesión a disco (`data/anki_session.json`)
usando la API in-process de Anki —viva mientras el hook corre, a diferencia de
AnkiConnect— con las notas estudiadas, sus cards y los contadores del día.
`anki_notion_sync` sirve las cuatro acciones que usa (`findNotes`, `notesInfo`,
`findCards`, `cardsInfo`) desde ese snapshot en cuanto AnkiConnect falla, **en
cualquier punto de la corrida**; `learner_profile_update` y `run_all` hacen lo
mismo para sus métricas. El snapshot se ignora si no es de hoy.

Resultado: cerrar Anki inmediatamente después de estudiar es ahora un camino
soportado, no una carrera perdida.

## Riesgos

1. **Requiere reiniciar Anki una vez** para cargar el add-on nuevo (symlink ya apunta al repo).
2. **`python3` del login shell sin `requests`** → el pipeline muere temprano; el
   comando manual lo revela de inmediato. (`requirements.txt` ya existe.)
3. **Primera notificación** puede pedir permiso de notificaciones una única vez.
4. **Si Anki crashea** (no cierre limpio), no hay hook → no hay run. El siguiente
   fin de sesión o el comando manual recuperan el día completo (rated:1).
5. **Plan diario aún no genera nada**: requiere `ANTHROPIC_API_KEY` (B-OUT-1).
   El hook existe y loguea el skip; al poner la key, se conecta el planner sin
   tocar esta automatización.

## Recuperación manual

```bash
python3 run_all.py session-end            # mismo camino que el add-on (respeta idempotencia)
python3 run_all.py session-end --force    # re-procesa aunque el estado diga ok
python3 run_all.py morning                # legacy directo, sigue intacto
tail -50 logs/$(date +%F).log             # diagnóstico
cat logs/.session_state.json              # último estado (ok/pending/failed)
```

## Criterios de aceptación

1. Estudiar en Anki y volver al deck browser → sin tocar nada más: VOCAB
   sincronizado, Writing y Reading del día creados/actualizados,
   `data/learner_profile.json` con la entrada de hoy, notificación macOS de éxito.
2. Repetir el disparo sin nuevas reviews → salida en <1 s, cero escrituras a Notion.
3. Segunda sesión de estudio el mismo día → re-procesa solo lo nuevo, sin duplicar
   páginas ni registros.
4. Cerrar Anki inmediatamente tras estudiar → estado `pending` + notificación
   honesta; el siguiente disparo o el comando manual completa el día sin pérdida.
5. Notion caído → notificación de fallo, log con detalle, re-ejecución manual segura.
6. Anki nunca se bloquea ni muestra errores por el pipeline.
7. `grep -r NOTION_TOKEN anki_addon/` → sin resultados.
