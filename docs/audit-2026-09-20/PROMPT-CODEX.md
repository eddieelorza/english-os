Trabaja en English_Automation_v2. Mejora la fiabilidad y continuidad de English OS basándote en `docs/audit-2026-09-20/ANALISIS.md` y sus nueve capturas. Lee AGENTS.md, README.md, PRODUCT.md, DESIGN.md y los ADR vigentes. Parte del código actual, incluidos cambios sin commit; no los sobrescribas ni reviertas. El sistema vigente es local con SQLite: los documentos históricos de Anki/Notion no describen producción actual.

Objetivo: que un estudiante A2/B1 pueda escribir, consultar vocabulario, volver y recibir feedback honesto sin perder su trabajo ni contaminar la estimación de nivel.

Implementa primero:

1. Estados de evaluación explícitos por oración (correcta, corregida, pendiente/inválida). En app/writing.py, una corrección traducida descartada no puede devolver un acierto. En GuidedWriting.tsx y el contrato API conserva el estado hasta SQLite y el resumen. Un fallo del tutor no es un error del estudiante ni una respuesta correcta. Mantén reintento y continuación; muestra cuántas oraciones faltan por revisar.
2. Separa palabras producidas de palabras válidamente evaluadas. Revisa writing.finish y model.errors: textos parcialmente evaluados no deben contar como textos perfectos. Conserva originales y correcciones. El reintento debe ser idempotente y no duplicar palabras, errores ni sesiones. No recalcules ni migres datos personales sin presentar el alcance concreto.
3. Guarda y recupera borradores guiados: tarea, paso, texto actual, respuestas y evaluación pendiente. Deben sobrevivir a navegación y recarga. Guardar un borrador no modifica racha, nivel, sesiones completadas ni FSRS. Ofrece continuar y descartar explícitamente.
4. Refresca History tras guardar Writing: la entrada debe aparecer inmediatamente y una sola vez.

Después, mejoras pequeñas:
- Alinea Today con el writing de una oración a la vez; ofrece siguiente actividad y final claro, conservando interfaz en inglés, español según las convenciones vigentes y estética de cuaderno.
- En cierre de Practice ofrece una microtarea opcional para aplicar el error en otro contexto; evita párrafos largos obligatorios y no confundas reconocimiento con producción independiente.
- Reproduce en un entorno ficticio el fallo de guardado de ComprehensionQuiz; si se confirma, elimina el catch silencioso y añade estado visible y reintento sin duplicados.
- Aclara qué cubre el tiempo estimado del repaso, sin alterar FSRS por razones cosméticas.

Seguridad de la prueba: usa base y rutas temporales NUEVAS, proveedor de IA determinista y trabajadores/exportaciones aislados. No abras ni escribas data/english.db, no uses el puerto de producción 8770, no ejecutes morning/reset/sync-used y no modifiques Anki, Notion ni el vault real. El servidor ficticio anterior puede estar apagado: crea tu propio entorno reproducible. No hagas commits automáticos.

Validación mínima: traducción inválida; timeout del corrector; sesión parcialmente evaluada; reintento de corrección y guardado; navegación y recarga con borrador; historial actualizado; regresión del camino normal; fallo de guardado de quiz. Prueba estados visibles en navegador además de pruebas de contrato/persistencia. Verifica que textos pendientes no mejoran artificialmente la precisión al alcanzar la muestra mínima. Comprueba teclado y foco del feedback; no declares accesibilidad completa sin medirla.

Entrega cambios concretos, pruebas y resultados, capturas de los casos corregidos y límites pendientes. Prioriza los cuatro primeros puntos antes de proponer nuevas funciones o un rediseño general.
