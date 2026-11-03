# ADR-017 — The Annotated Edition, y el teléfono sin login

- **Estado**: identidad implementada (Hito 1, 2026-11-02); acceso móvil decidido, **sin instalar**
- **Contexto**: rediseño de producto; continúa ADR-013 (app local)
- **Decide**: Eddie, sobre la auditoría del 2026-11-02 (26/40 en heurísticas)

## D1 — Evolucionar la identidad, no reemplazarla

El mundo del Assimil Workbook es lo más propio que tiene el producto: el papel,
las reglas en vez de tarjetas, la tinta de estado, el español cubierto, los
números honestos. Lo que fallaba era el volumen, no los huesos, así que se
conservan y baja lo que gritaba (pared cobalto, Archivo 800, texto de 10-11 px).
Detalle en `DESIGN.md` → *The Annotated Edition*.

## D2 — Sin pantallas de autenticación

El brief pedía login, registro y recuperación de contraseña. La app no tiene
autenticación, escucha sólo en `127.0.0.1` y tiene un usuario. Pantallas sin un
backend real serían decorado, y un backend real (usuarios, sesiones, correo)
cambiaría la arquitectura para resolver un problema que no existe.

## D3 — El teléfono llega por Tailscale Serve

Una UI móvil no sirve si el teléfono no alcanza el servidor. Abrirlo a la red
local no basta: el micrófono del navegador exige HTTPS, así que Speaking y
Shadowing no grabarían, y sin auth cualquiera en esa red entraría.

`tailscale serve` da HTTPS y limita el acceso a los dispositivos de Eddie, sin
tocar el `127.0.0.1` de ADR-013 ni añadir login. Falta instalarlo y probarlo; el
Mac tiene que estar encendido.

**Volver a esta decisión** si alguna vez hay un segundo usuario: entonces sí
hace falta autenticación de verdad, y esta ADR deja de aplicar.
