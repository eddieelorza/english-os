# ADR-018 — English OS 2.0: el mazo se congela, las glosas se auditan, y lo que no se construye

- **Estado**: decidido (2026-11-22); M0 implementado (`cfac07f`); MVP en curso
- **Contexto**: auditoría del 2026-11-22 sobre el repo y `data/english.db`. Continúa ADR-014/015 (carga) y ADR-017 (identidad)
- **Decide**: Eddie, sobre la propuesta del 2026-11-22

## Lo que se midió

| Dato | Valor |
|---|---|
| Palabras NEW / total | 2,803 / 3,108 |
| Días de estudio por semana (sem. 39→46) | 5, 6, 4, 2, 0, 2, 0, 2 |
| Último writing / speaking en la app | 2026-08-24 / 2026-08-27 |
| Lecturas terminadas / generadas | 12 / 124 |
| Acierto en pasos de aprendizaje | 39.8% |
| Glosas ES que no coinciden con la traducción de su propio ejemplo | 613 de 2,397 (`cabin` → "Cabina", ejemplo: "cabaña") |
| Imágenes del mazo en disco / mostradas en la UI | 3,103 / 0 |

La relación entre glosa desalineada y lapsos existe pero no es concluyente
(0.76 vs 0.61 lapsos promedio, 49 casos): la reparación se trata como
experimento, no como certeza.

## D1 — El mazo de cuentos deja de alimentar palabras nuevas

"4000 Essential English Words" es vocabulario de cuentos (`quarrel`, `coal`,
`beast`), no de reuniones de ingeniería. Las palabras nuevas salen de lo que
Eddie **encuentra** (lecturas, audio, conversación) y, más adelante, de un
léxico de trabajo curado. Implementación: `deck_new_source = encountered`
(por defecto) sólo admite como nueva una palabra vista en una lectura
terminada o añadida fuera del mazo; `deck` devuelve el comportamiento anterior.
Hoy: 83 elegibles, 2,017 en reserva. Nada se borra.

## D2 — Las glosas se auditan con propuesta, validación y revisión humana

Detector determinista → propuesta del modelo → validación determinista (la
glosa tiene que aparecer en la traducción del ejemplo) → Eddie acepta, edita o
rechaza. Aceptar escribe en `words` y guarda el valor anterior en `senses`:
cada cambio se puede deshacer. Alcance: las palabras activas, no las 3,108.

## D3 — Dirección visual: evolucionar The Annotated Edition

No hay segundo sistema de diseño. Lo que cambia es la variedad de interacción
(respuesta escrita, audio primero, hueco), no la identidad.

## D4 — Sin XP ni niveles

Se mantiene el no-objetivo de `PRODUCT.md`. El progreso visible son bandas por
habilidad y palabras por nivel de conocimiento (reconozco / recuerdo / uso).
La unidad de constancia es la semana en ritmo (5 de 7).

## D5 — Claude Code se queda en `brief/submit`

No se construye un puente navegador → CLI. ADR-016 ya midió 12 s y ~47k tokens
de sobrecarga por llamada; el modelo actual (la app expone, Claude Code jala y
entrega) es además el seguro.

## Lo que no se construye

Ocho agentes (son un tutor y un escritor por lotes sobre código determinista) ·
puntaje numérico de pronunciación · generación de imágenes (primero se usan las
del mazo) · reescritura del frontend.

## Cómo se sabrá si funcionó

Experimentos por ítem, con Eddie como único sujeto: glosa reparada vs sin
reparar (lapsos y prueba a 30 días); respuesta escrita vs auto-calificada
(prueba productiva a 7 y 30 días). Y la compuerta de producto: ≥ 4 días por
semana y ≥ 60% del material terminado tras cuatro semanas de sesión guiada.
