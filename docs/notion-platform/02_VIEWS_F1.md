# Vistas de Fase 1 — para crear en la UI de Notion (5 min)

> La API de Notion no puede crear ni configurar vistas (limitación oficial), así
> que estas se crean a mano una sola vez. Alternativa: autorizar el conector de
> Notion en claude.ai (soporta crear vistas) y Claude las monta por ti.

Debajo del callout 🎯 TODAY, agrega bloques `/linked view of database`:

**1. Vocabulary — Hoy** (linked view de VOCABULARY MASTER)
- Filtro: `Synced On` **is** `Today`  ← (no uses `Last Reviewed`: es last_edited_time)
- Vista: Table. Columnas visibles: Word, Meaning (EN), Pronunciation, Times Used
- Orden: Word A→Z

**2. Daily Plan — Esta semana** (linked view de Daily Plan)
- Filtro: `Date` **is on or after** `One week ago`
- Vista: Table. Columnas: Session, Status, Format, Words Today, Again Rate, Recommendation
- Orden: Date ↓

**3. Reading — Pendientes** (linked view de Reading Hub)
- Filtro: `Status` **is not** `Done`
- Vista: List. Orden: Date ↓

**4. Writing — Sin corregir** (linked view de Writing Practice)
- Filtro: `Corrected` **is** `Unchecked`, `Date` is on or after One month ago
- Vista: List. Orden: Date ↓

Sugerencia de layout: mete las vistas 2-4 dentro de un toggle "📚 Esta semana"
para que el tope de la página quede limpio (prioridad visual: qué hago hoy).
