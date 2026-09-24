# ADR-013 — English OS como app local, sin `npm`

- **Estado**: aceptado (implementado 2026-08-29)
- **Contexto**: Fase 5, tras ADR-012 (Notion apagado)
- **Decide**: Eddie, tras ver las mediciones

## Contexto

Eddie pidió dejar de arrancar la app a mano y que se abriera al entrar, pero
con una preocupación explícita: **no desgastar el Mac ni gastar batería**, y
que sólo funcionara "cuando haya interacción".

### Qué se midió antes de decidir

Sobre su MacBook Pro M5 (16 GB), 60 segundos de tiempo de CPU real y mientras
él estudiaba (así que es cota alta, no reposo puro):

| proceso | CPU en 60 s | RAM |
|---|---|---|
| uvicorn | 0.18 s | 18 MB |
| vite (dev server) | 0.05 s | 59 MB |
| ollama serve | 0.01 s | 8 MB |

**0.24 s de CPU por minuto ≈ 0.4 % de un núcleo**, 85 MB de RAM. Menos que una
pestaña de fondo.

**Conclusión 1**: la preocupación estaba mal dirigida. Tener la app encendida
no cuesta nada medible. Lo que sí cuesta es generar material: Ollama carga
`qwen2.5:7b`, **4.7 GB de RAM** y CPU sostenida un par de minutos — y eso no
cambia con cómo se empaquete la app.

**Conclusión 2**: `npm` hacía falta por una sola razón, y tonta — **FastAPI no
servía el frontend compilado**. `frontend/dist` (800 KB) existía y no lo servía
nadie; Vite corría sólo para eso y para hacer proxy de `/api`.

**Conclusión 3**: el arranque en frío es de **0.15 s**, así que despertar por
demanda sería imperceptible… pero ver arriba: no hay nada que ahorrar.

## Decisiones

### D1 — FastAPI sirve la app; Vite queda para desarrollar

Un comodín al final de `app/server.py` sirve `frontend/dist` y vuelve a
`index.html` en las rutas del router (`/review`, `/stats`…), que no existen
como archivo. Dos guardas que costaron su test cada una:

- **`/api` que no casa es 404**, no la página. Sin eso una ruta mal escrita
  devolvía HTML con un 200 y el fallo aparecía como "JSON inválido" muy lejos
  de su causa.
- **`resolve()` + `is_relative_to`** antes de servir un archivo por ruta del
  usuario. Un comodín que abre archivos es exactamente por donde entra `../`.

El comodín va al final del módulo a propósito: captura todo lo que no haya
casado antes, así que cualquier ruta `/api` declarada después quedaría muerta.

### D2 — Agente `launchd`, no una `.app` empaquetada

Se descartó PyInstaller/Tauri/Electron con datos: el venv pesa **1.0 GB**, y
**504 MB son `torch`** (más `onnxruntime` 75 MB y `transformers` 56 MB), que
sólo usa `app/speaking.py` y que **no se importa al arrancar** — es carga
perezosa, así que hoy no cuesta nada y empaquetarlo sí. No compraba nada
funcional sobre el agente.

`ProcessType=Adaptive` a propósito: `Background` mantendría el proceso
estrangulado y estudiar se sentiría lento; `Interactive` gastaría de más.
`KeepAlive` sólo ante salida no limpia, para que pararlo a mano no pelee con
launchd. Escucha sólo en `127.0.0.1`: la app no se asoma a la red de casa.

El icono del Dock es una `.app` de dos archivos que espera a que el servidor
responda antes de abrir el navegador — una pestaña con "no se puede conectar"
no dice qué hacer.

### D3 — Se descarta el apagado por inactividad (por ahora)

Era lo que Eddie pidió literalmente y `launchd` lo soporta nativo (activación
por socket). Se deja fuera porque **ahorra 0.4 % de un núcleo** y rompe algo
real: generar una lectura tarda 1-3 minutos, y un servidor que se apaga al
cerrar el navegador mataría el trabajo a medias. Volver a ello exigiría un
temporizador que espere a que la cola se vacíe. Queda apuntado, no hecho.

### D4 — `.env` se carga al importar el servidor

`AI_PROVIDER` y `OLLAMA_MODEL` viven en `.env` y sólo los cargaba
`run_all.py`. Un uvicorn a mano — o launchd, que no hereda tu shell — corría
sin ellos y elegía proveedor por su cuenta: fallo silencioso, porque la app
funciona igual y el material sale de otro sitio o de ninguno.

Aquí `.env` **no pisa** lo que ya esté en el entorno, al revés que en
`run_all.py`. Bajo launchd da lo mismo (no hereda nada), y a cambio importar
el módulo deja de poder secuestrar una variable puesta a propósito por un test.

## Consecuencias

- `npm` deja de hacer falta para **usar** la app; sigue haciendo falta para
  desarrollarla, y **hay que recompilar** (`npm run build --prefix frontend`)
  para que un cambio de UI llegue a la app instalada. Es el precio de no
  depender de Vite.
- `node_modules` (192 MB) ya no participa en el uso diario.
- Instalar/desinstalar: `scripts/install_app.sh [uninstall]`. No usa sudo y no
  toca nada fuera del usuario.
