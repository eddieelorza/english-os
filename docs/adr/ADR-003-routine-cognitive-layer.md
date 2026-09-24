# ADR-003 — Capa cognitiva vía Claude Code Routine (sin API key)

> Estado: **implementado** (2026-07-29). Routine `trig_01HvnwuNc1PinNW1gGnLQ2AE`
> (claude.ai/code/routines) con conector Notion (solo), modelo claude-sonnet-5,
> cron de respaldo 03:30 UTC. Prompt versionado en `docs/routine-prompt.md`.
> API trigger **verificado end-to-end** (2026-07-29 22:52 CDMX, HTTP 200).
>
> Nota de implementación (costó un 400): el endpoint exige **tres** headers, no
> dos — `Authorization: Bearer <token>`, `anthropic-version: 2023-06-01` y
> `anthropic-beta: experimental-cc-routine-2026-04-01`. Sin `anthropic-version`
> responde `400 {"message":"anthropic-version: header is required"}`, que es
> fácil de confundir con un problema de token. El token vive solo en `.env`
> (`ROUTINE_FIRE_TOKEN`); `.env.example` lleva la clave vacía.
> Corrige la decisión B-OUT-1: NO se usará `ANTHROPIC_API_KEY` ni la API de pago.
> Todo el trabajo cognitivo corre contra la suscripción Claude Max de Eddie.

## Verificaciones previas (hechos, no suposiciones)

| # | Verificación | Resultado |
|---|---|---|
| 1 | Claude Code on the web + Routines habilitados en la cuenta | ✅ Confirmado operativamente: el entorno cloud `Default` (`env_013WCTDXvHHnkk6uEoFd92sq`, anthropic_cloud) existe/se aprovisionó para esta cuenta y el sistema de routines respondió. |
| 2 | CLI autenticado por suscripción, no por API key | ✅ CLI 2.1.185 con `oauthAccount` presente (edd.elorza@gmail.com); `ANTHROPIC_API_KEY` no existe ni en el entorno ni en `.env`. |
| 3 | Sin usage credits / facturación extra | ✅ Diseño no activa nada; las routines consumen la cuota Max. **OJO**: hay un *daily cap* de runs; sin credits, los runs por encima del cap se rechazan (comportamiento deseado: fallback local). |
| 4 | API trigger HTTP documentado | ✅ `POST https://api.anthropic.com/v1/claude_code/routines/{routine-id}/fire` con **Bearer token por-routine** (se genera/revoca en claude.ai/code/routines). Beta: header `experimental-cc-routine-2026-04-01`. Fuente: code.claude.com/docs/en/routines.md. |
| 5 | Acceso a Notion desde la nube | Conector oficial de Notion vía MCP (credenciales por proxy seguro). **Hoy NO está conectado** — prerequisito de Eddie. Las env vars de cloud environments son legibles por cualquier usuario del environment y la doc desaconseja poner credenciales ahí → **no pondremos `NOTION_TOKEN` en el environment ni en el payload**. |
| 6 | `claude -p` headless con OAuth Max | ✅ Soportado oficialmente sin API key (alternativa B viable). |

## Alternativa A — Routine en la nube disparada por HTTP (recomendada)

```
Anki add-on ─► run_all.py session-end (local, determinístico)
                 ├─ sync VOCAB + páginas + learner profile + Daily Plan   (ya existe)
                 ├─ escribe session_id y contexto EN la fila Daily Plan   (nuevo)
                 ├─ POST …/routines/{id}/fire  (Bearer ROUTINE_FIRE_TOKEN)(nuevo)
                 ├─ guarda estado + notificación "material en camino"     (ajuste)
                 └─ exit  ← la Mac ya puede cerrarse
                          ▼ (nube, minutos después)
              Routine (Sonnet, conector Notion MCP, sin repo, sin secretos):
                 1. lee la fila Daily Plan de hoy (toda su entrada está ahí)
                 2. si "AI Status" ya es Done para este session_id → sale (idempotente)
                 3. analiza learner profile*, errores objetivo, palabras del día
                 4. genera la historia en Reading, actividades en Writing,
                    recomendación refinada en Daily Plan
                 5. marca AI Status=Done + session_id procesado
```

\* El contexto del perfil viaja **dentro de Notion**, no en el payload: el paso
local ya escribe reviews/again-rate/palabras/formato en la fila Daily Plan.
El POST lleva solo `{session_id}` — o nada, si el endpoint no acepta body
(verificación pendiente en implementación; el diseño no depende de ello).

- **Seguridad**: ningún secreto viaja en el payload; Notion se accede por el
  conector OAuth oficial (proxy de Anthropic); el único secreto local nuevo es
  `ROUTINE_FIRE_TOKEN` en `.env` (revocable en la UI). AnkiConnect jamás se
  expone: la nube nunca habla con la Mac — el canal de vuelta es Notion.
- **Confiabilidad / errores**: si el POST falla (red, cap diario, 5xx) →
  reintento con backoff (3 intentos) y luego **fallback al estado actual**: la
  recomendación por reglas y el placeholder de Reading quedan como hoy; el
  material se genera al invocar a Claude manualmente ("dame la lectura del
  día"). El pipeline local nunca depende de la routine (restricción 10).
- **Mac cerrada**: la Mac solo necesita estar despierta ~30 s (parte local +
  POST). La generación corre en la nube — puedes cerrar la laptop al terminar Anki.
- **Consumo Max**: 1 run/día ≈ una sesión corta de Claude Code. Comparte tu
  cuota Max y el daily cap de routines; sin credits el exceso se rechaza (y cae
  al fallback, sin costo).
- **Duplicados**: `session_id = fecha + reviews_procesadas` (el mismo contador
  de la idempotencia local). La routine lo compara contra la propiedad
  `AI Session` de la fila Daily Plan antes de generar; el paso local además no
  re-dispara si el estado ya es `ok` para ese contador. Doble candado.
- **Validación de resultados** (Python, siguiente session-end o `sync-used`):
  verifica que Reading tenga historia y que las palabras del día aparezcan;
  si no, marca `AI Status=Failed` y notifica.

## Alternativa B — `claude -p` local headless (OAuth Max)

El mismo paso cognitivo, pero como proceso local: `claude -p "<prompt>"` lanzado
por `session-end`, usando el repo y el `NotionClient` existente con el `.env` local.

- **Pros**: cero superficie nueva de auth (ni token de routine, ni conector);
  acceso directo al repo y a `data/learner_profile.json`; sin API beta; más simple.
- **Contras**: consume CPU/red de la Mac varios minutos; **muere si cierras la
  laptop justo al terminar Anki** (tu caso real); acopla la generación al estado
  de tu máquina; hay que gobernar permisos de herramientas en modo headless.
- Mismo consumo de cuota Max. Misma idempotencia posible.

## Recomendación

**A**, por tres razones: encaja tu criterio de UX (cerrar la laptop y que el
material aparezca), mantiene la generación fuera de tu máquina, y su modo de
fallo es benigno (cap alcanzado → fallback local, costo cero). **B queda
documentada como plan B real**: si la API beta de triggers rompe o resulta
inestable, B se implementa en ~1 hora porque el prompt y la validación son los
mismos. No construiremos ambas a la vez (P5: lo más simple que enseñe).

Riesgo principal de A, dicho sin maquillaje: **el endpoint de fire es beta**
(header experimental, breaking changes anunciados). Lo aceptamos porque el
fallback es el statu quo, no una caída del sistema.

## Prerequisitos (acciones de Eddie, ~10 min)

1. Conectar el **conector oficial de Notion** en claude.ai/customize/connectors
   (con acceso a ENGLISH SYSTEM y sus DBs).
2. Crear la routine en claude.ai/code/routines y **generar el API trigger token**;
   pegarlo en `.env` como `ROUTINE_FIRE_TOKEN=` junto con `ROUTINE_ID=`.
3. Confirmar en claude.ai/settings/usage que no hay usage credits activados
   (para que el exceso se rechace en vez de facturarse).

## Cambios de implementación (cuando apruebes)

- `scripts/daily_plan_update.py`: escribir `AI Session` (session_id) y
  `AI Status` (Pending) en la fila Daily Plan. +2 propiedades en la DB.
- `run_all.py session-end`: nuevo paso `fire_routine()` (urllib, 3 reintentos,
  nunca fatal) + notificación diferenciada ("material en camino" vs "modo local").
- Prompt de la routine (autocontenido, versionado en `docs/routine-prompt.md`):
  reglas pedagógicas de CLAUDE.md (nivel, 330-370 palabras, TODAS las palabras,
  formato de actividades del PROMPT de Eddie) + protocolo de idempotencia.
- Validador post-hoc en el siguiente run local.

## Criterios de aceptación

1. Terminas Anki, cierras la laptop; ≤10 min después la historia del día está
   en Reading, las actividades en Writing y la recomendación refinada en Daily
   Plan, con `AI Status=Done`. Sin abrir chat ni terminal.
2. El mismo `session_id` disparado dos veces genera contenido **una** sola vez.
3. Con el token revocado o cap alcanzado: el pipeline local termina ok, notifica
   "modo local", y el día es utilizable (flujo actual con Claude manual).
4. `grep -r NOTION_TOKEN` sobre payloads/prompt/environment de la routine → nada.
5. AnkiConnect sigue escuchando solo en localhost; ningún puerto nuevo abierto.
6. Un mes de operación sin usage credits: facturación extra = $0.
