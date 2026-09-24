# Product Vision — AI Personal English Coach

> Documento 1 de 5. Estado: **borrador para aprobación de Eddie**.
> Sucesores: 02_PRD_BACKLOG.md · 03_ARCHITECTURE_DATA.md · 04_LEARNING_ENGINE.md · 05_ROADMAP.md

---

## 1. El problema

Eddie está en A2/B1 y quiere llegar a B2 sólido y luego C1. Tiene disciplina diaria
(Anki sin fallar), herramientas (Anki, Notion, Claude) y un pipeline que genera
material. Lo que no tiene es lo que sí tendría con un tutor humano competente:

1. **Alguien que observe su desempeño** — no su actividad — y detecte patrones.
2. **Alguien que decida qué practicar hoy** basándose en esos patrones.
3. **Alguien que lo obligue a producir** (hablar, escribir libre) fuera de su zona cómoda.
4. **Alguien que le diga con evidencia si está mejorando** o solo acumulando material.

El problema no es acceso a contenido de inglés — el mundo está inundado de contenido.
El problema es que **el contenido no toma decisiones**. Un tutor sí.

**Enunciado del problema en una línea:**
*"Estudio inglés todos los días y no sé si estoy avanzando, porque nada en mi
sistema observa lo que produzco ni adapta lo que me pide."*

## 2. Para quién

Para Eddie. Uno solo. Esto importa porque elimina el 80% de la complejidad de un
producto real: sin auth, sin multi-tenancy, sin onboarding genérico, sin diseñar
para el mínimo común denominador. Cada decisión se optimiza para:

- Hispanohablante, interferencia L1 español (artículos, preposiciones, orden, falsos amigos).
- ~60-75 min/día disponibles, por la mañana, en una Mac.
- Perfil técnico: la terminal no es fricción, es interfaz.
- Motivación actual alta, pero el sistema debe sobrevivir a los meses donde no lo esté.
- Horizonte: 2 años (B2 sólido ~12 meses, C1 funcional ~24).

Si algún día esto se generaliza a otros usuarios, será una decisión nueva con
documentos nuevos. **No diseñamos para ese futuro hipotético.**

## 3. Filosofía del producto

Cinco principios. Toda funcionalidad futura se valida contra ellos; si no pasa
al menos cuatro, no se construye.

### P1 · Producción sobre reconocimiento
El sistema existe para hacerte producir inglés (hablar, escribir, recuperar) y
procesar lo que produces. El input (lectura, listening) está al servicio de la
producción, no al revés. Regla práctica: **cada sesión diaria contiene al menos
un acto de producción libre evaluada**. Un día sin producir es un día de
mantenimiento, no de avance.
*Base: Output Hypothesis (Swain); testing effect (Roediger & Karpicke).*

### P2 · El dato se captura como subproducto, nunca como tarea
Ninguna métrica requiere que Eddie "registre" nada. Si medir algo exige un paso
manual extra, esa métrica no existe. El warm-up productivo ES la medición de
recall; la corrección de writing ES la fuente del perfil de errores.
*Base: la fricción mata hábitos antes que la dificultad (Fogg, comportamiento).*

### P3 · Un cerebro, muchos brazos
Un solo componente (el Learning Engine / Planner) toma todas las decisiones
pedagógicas: qué, cuánto, a qué nivel, cuándo repetir. Los demás módulos generan,
evalúan o miden, pero **no deciden**. Prohibido que un generador elija su propia
dificultad. Esto evita el estado actual: cinco motores independientes sin entrenador.

### P4 · Evidencia sobre sensación
La dificultad sube cuando las métricas de una ventana de 2+ semanas lo justifican,
no cuando Eddie se siente listo ni cuando el sistema "cree" que toca. Ancla externa
mensual (probe estandarizado) para que el sistema no se califique a sí mismo.
*Base: formative assessment (Black & Wiliam); CAF measures.*

### P5 · Lo más simple que enseñe
Entre dos diseños con el mismo resultado pedagógico, gana el más simple, siempre.
Anki sigue siendo el SRS (no reinventamos repetición espaciada). Notion sigue
siendo la UI (no construimos frontend). Claude es el evaluador/interlocutor
(no entrenamos modelos). El código propio es solo el pegamento y el cerebro.
Corolario: **se permite eliminar funcionalidad existente** si no enseña
(candidato ya identificado: ejercicios fill-in-the-blank).

## 4. Qué lo hace diferente

| | Duolingo / Babbel | Anki solo | Tutor humano | **Este sistema** |
|---|---|---|---|---|
| Adapta al desempeño | Superficialmente (ítems) | Solo memoria de cards | Sí, con criterio | Sí, con reglas explícitas + LLM |
| Producción libre evaluada | Mínima | Ninguna | Sí | Sí, diaria (writing + speaking) |
| Conoce TUS errores recurrentes | No | No | Sí, informalmente | Sí, estructurado y persistente |
| Contenido de tus intereses | No | Solo si lo haces tú | A veces | Sí (input real que tú eliges) |
| Costo | $10-15/mes | Gratis | $600+/mes | ~$5/mes de API |
| Disponibilidad | 24/7 | 24/7 | 1-2 h/semana | 24/7 |
| Optimiza para | Retención en la app | Retención de cards | Tu aprendizaje | Tu aprendizaje |

La celda que define el producto es la última fila. Duolingo optimiza engagement
porque su negocio es tu atención. Este sistema no tiene ese conflicto de interés:
su única métrica de éxito es tu nivel real de inglés.

**La ventaja injusta**: un LLM de frontera puede evaluar producción libre
(writing y speaking) con calidad cercana a un profesor, a costo marginal cero,
todos los días. Ningún producto masivo ofrece eso hoy sin diluirlo. Un sistema
personal sí puede. Todo el diseño gira alrededor de explotar esa ventaja.

## 5. Definición de éxito

- **Norte (24 meses)**: C1 funcional — certificable si Eddie quiere (CAE / IELTS 7+).
- **Intermedio (12 meses)**: B2 sólido verificado por probe externo (EFSET B2 alto
  sostenido en 3 mediciones mensuales consecutivas), no por métricas internas.
- **Guardarraíl de hábito**: ≥ 5 sesiones/semana sostenidas. Si el sistema es tan
  ambicioso que Eddie deja de usarlo, el sistema fracasó aunque su pedagogía sea perfecta.
- **Métrica de producto (proxy trimestral)**: errores/100 palabras en producción
  libre ↓ y WPM hablado ↑, ambos en tendencia sostenida.

## 6. No-goals (explícitos y vinculantes)

> ⚠️ **Enmienda 2026-08-20** ([ADR-006](adr/ADR-006-english-os-local-first.md)):
> los no-goals #1 y #3 quedan enmendados — habrá app local (justificación P1/P4/P5)
> y Anki/Notion se reemplazan gradualmente. #2, #4, #5, #6 y #7 siguen vigentes.

1. **No es una app**. Terminal + Notion + Anki. Sin frontend propio, sin mobile.
2. **No es multiusuario**. Cero generalización especulativa.
3. **No reemplaza Anki ni Notion**. Orquesta, no sustituye.
4. **No entrena modelos ni hace ML propio**. Las reglas adaptativas son `if` con
   ventanas de datos; la inteligencia difusa la pone Claude vía API.
5. **No gamifica con presión** (streaks punitivos, ligas). El motivador es progreso
   visible real, no ansiedad manufacturada.
6. **No persigue pronunciación de precisión fonética** (análisis de formantes, etc.).
   Shadowing + feedback de transcripción cubre el 80% que importa hasta C1.
7. **No automatiza la voluntad**. El sistema decide QUÉ practicar; sentarse a
   practicar sigue siendo trabajo de Eddie. Ningún diseño elimina eso.

---

*Aprobación pendiente. Cambios a este documento después de aprobado requieren
justificar qué principio (P1-P5) motiva el cambio.*
