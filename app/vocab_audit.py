"""Auditoría de glosas: el modelo propone, el código valida y el alumno decide."""

from __future__ import annotations

import json
import re
import sqlite3

from app import ai, db, experiments, glossary

POSITIONS = ("noun", "verb", "adjective", "adverb", "phrase", "other")

SYSTEM = """Eres un tutor de inglés para un hispanohablante de nivel B1–B2.
Propones una reparación de la glosa de una tarjeta; el alumno decidirá.

Regla dura: gloss_es es la palabra o frase corta EN ESPAÑOL (máximo 4
palabras) que la traducción de ESTE ejemplo usa para la palabra inglesa,
en forma de diccionario (infinitivo para verbos). No elijas otra acepción.
Forma de diccionario: nunca la frase copiada; sin «no» ni pronombres
delante; un verbo lleva sólo el infinitivo y las palabras que forman parte
de su significado («dar palmaditas», «alardear de»), sin relleno.
Si falta la traducción, usa el sentido del ejemplo inglés.
pos: noun, verb, adjective, adverb, phrase u other.
definition_en: definición en inglés sencillo, de 6 a 14 palabras, sin usar
la palabra definida ni sus derivados; una frase sin punto final. Empieza
con 'to' para verbos, 'a' o 'the' para sustantivos. No un sinónimo suelto.
note_es: una línea corta sobre una trampa para hispanohablantes (falso
amigo, uso distinto al del español), no sobre el registro del inglés; o vacío.
imageable: true si una imagen puede mostrarlo (objeto concreto o acción),
false si no.
second: sólo si hay otra acepción frecuente que un alumno B1–B2 encontrará;
incluye gloss_es y un ejemplo example_en que contenga la palabra, con su
traducción example_es. En otro caso, null.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "pos": {"type": "string", "enum": list(POSITIONS)},
        "gloss_es": {"type": "string"},
        "definition_en": {"type": "string"},
        "note_es": {"type": "string"},
        "imageable": {"type": "boolean"},
        "second": {
            "anyOf": [
                {"type": "null"},
                {"type": "object", "properties": {
                    "gloss_es": {"type": "string"},
                    "example_en": {"type": "string"},
                    "example_es": {"type": "string"}},
                 "required": ["gloss_es", "example_en", "example_es"]},
            ]},
    },
    "required": ["pos", "gloss_es", "definition_en", "note_es", "imageable"],
}


def flags(row) -> list[str]:
    """Señales heurísticas, no un análisis semántico ni un lematizador.

    Las raíces toleran tildes y algunas flexiones, pero pierden cambios
    irregulares (miedo/temo) y pueden coincidir por accidente. En frases
    basta un token: «hambre» hace coincidir «morir de hambre»/«murieron».
    """
    row = dict(row)
    gloss = (row.get("meaning_es") or "").strip()
    example = (row.get("example_es") or "").strip()
    found = []
    if not gloss:
        found.append("no_gloss")
    elif example:
        stems = []
        for token in re.findall(r"[^\W\d_]+", gloss):
            token = glossary._fold(token)
            if token.endswith("se"):
                token = token[:-2]
            if len(token) >= 3:
                # Las palabras largas pierden una letra más: «avergonzado»
                # tiene que reconocer «avergonzó».
                cut = 3 if len(token) >= 8 else 2
                stems.append(token[:max(3, len(token) - cut)])
        if not any(stem in glossary._fold(example) for stem in stems):
            found.append("gloss_not_in_example")
    if not (row.get("meaning_en") or "").strip():
        found.append("no_definition")
    return found


def candidates(conn: sqlite3.Connection, limit: "int | None" = None) -> list:
    """Sólo palabras en juego, con ejemplo y sin auditoría anterior."""
    rows = conn.execute(
        "SELECT w.* FROM words w "
        "WHERE (fsrs_card IS NOT NULL OR seen_in_text IS NOT NULL) "
        "AND example_en IS NOT NULL AND TRIM(example_en) != '' "
        "AND NOT EXISTS (SELECT 1 FROM senses s WHERE s.word_id=w.id) "
        "ORDER BY COALESCE(lapses, 0) DESC, COALESCE(difficulty, 0) DESC, w.id"
    ).fetchall()
    flagged = [row for row in rows if any(f in flags(row) for f in
               ("no_gloss", "gloss_not_in_example"))]
    # E1: entre las palabras en estudio con la glosa desalineada, la mitad de
    # control conserva su glosa; sólo el grupo «repair» llega a la cola.
    kept = [row for row in flagged if row["fsrs_card"] is None
            or experiments.arm(conn, "E1", row["id"]) == "repair"]
    conn.commit()
    return kept[:limit]


_LEADING = {"no", "se", "me", "te", "le", "les", "nos"}
_FILLER = {"un", "una", "unos", "unas", "poco", "algo"}


def _gloss_problem(gloss) -> "str | None":
    if not isinstance(gloss, str) or not gloss.strip():
        return "gloss_es vacía"
    if len(gloss.split()) > 4:
        return "gloss_es demasiado larga (máximo 4 palabras)"
    return None


def _problem(result, row) -> "str | None":
    """Valida también la forma: un JSON válido puede tener campos erróneos."""
    if not isinstance(result, dict):
        return "la propuesta no es un objeto"
    why = _gloss_problem(result.get("gloss_es"))
    if why:
        return why
    if "gloss_not_in_example" in flags({
            "meaning_es": result["gloss_es"], "example_es": row["example_es"]}):
        return "gloss_not_in_example: gloss_es no aparece en example_es"
    # La regla del ejemplo también premia copiar la frase («no se encontraba»).
    # ponytail: rechaza también «no obstante»; esas se omiten, no se enseñan mal.
    tokens = [glossary._fold(t) for t in result["gloss_es"].split()]
    if tokens[0] in _LEADING:
        return "gloss_es no está en forma de diccionario: parece copiada de la frase"
    definition = result.get("definition_en")
    if not isinstance(definition, str):
        return "definition_en debe ser texto"
    why = glossary.problem(definition, row["word"])
    if why:
        return f"definition_en: {why}"
    if result.get("pos") not in POSITIONS:
        return "pos no permitido"
    # Sin esto la regla del ejemplo empuja al modelo a devolver la forma
    # conjugada («maldijo») para pasar; un verbo irregular se salta, no se
    # enseña mal.
    if result["pos"] == "verb":
        head = glossary._fold(result["gloss_es"].split()[0])
        if head.endswith("se"):
            head = head[:-2]
        if not head.endswith(("ar", "er", "ir")):
            return "gloss_es de un verbo debe ir en infinitivo"
        # ponytail: también cae «dar un paseo»; se omite antes que «dar un poco».
        if _FILLER & set(tokens[1:]):
            return "gloss_es de un verbo lleva relleno («un», «poco», «algo»)"
    if not isinstance(result.get("imageable"), bool):
        return "imageable debe ser booleano"
    if not isinstance(result.get("note_es"), str):
        return "note_es debe ser texto (puede estar vacío)"
    second = result.get("second")
    if second is not None:
        if not isinstance(second, dict) or any(
                not isinstance(second.get(k), str) or not second[k].strip()
                for k in ("gloss_es", "example_en", "example_es")):
            return "second necesita gloss_es, example_en y example_es no vacíos"
        word = glossary._fold(row["word"])
        if word[:max(3, len(word) - 2)] not in glossary._fold(second["example_en"]):
            return "second.example_en no contiene la palabra (raíz)"
        why = _gloss_problem(second["gloss_es"])
        if why:
            return f"second.{why}"
        if "gloss_not_in_example" in flags({
                "meaning_es": second["gloss_es"], "example_es": second["example_es"]}):
            return "second.gloss_es no aparece en second.example_es"
    return None


def propose(conn: sqlite3.Connection, limit: int = 20) -> dict:
    """Hasta tres intentos por palabra; nunca cambia `words`. Cuenta palabras."""
    provider = ai.get_provider("vocab_audit")
    proposed, skipped = 0, []
    for row in candidates(conn, limit):
        result, why = None, None
        for attempt in range(3):
            extra = ("" if attempt == 0 else
                     f"\n\nTu intento anterior fue rechazado ({why}): "
                     f"{json.dumps(result, ensure_ascii=False)}. Corrígelo.")
            try:
                result = provider.generate_json(
                    SYSTEM,
                    f'Palabra: "{row["word"]}"\n'
                    f'Glosa actual: {row["meaning_es"]}\n'
                    f'Ejemplo inglés: {row["example_en"]}'
                    f'\nTraducción del ejemplo: {row["example_es"]}{extra}',
                    SCHEMA)
                why = _problem(result, row)
            except Exception as exc:  # noqa: BLE001 — una palabra no tumba el lote
                why = f"error: {exc}"
                break
            if why is None:
                break
        if why is not None:
            skipped.append((row["word"], why))
            continue
        with conn:
            # No mantenemos el candado durante la llamada al modelo. Si otro
            # lote se adelantó, su propuesta ya ocupa esta palabra.
            if not conn.in_transaction:
                conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM senses WHERE word_id=?", (row["id"],)).fetchone():
                continue
            ts, reasons = db.now_iso(), json.dumps(flags(row))
            conn.execute(
                "INSERT INTO senses (word_id, pos, gloss_es, definition_en, "
                "note_es, imageable, flags, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (row["id"], result["pos"], result["gloss_es"].strip(),
                 result["definition_en"].strip().rstrip("."),
                 result["note_es"].strip() or None, int(result["imageable"]), reasons, ts))
            second = result.get("second")
            if second is not None:
                conn.execute(
                    "INSERT INTO senses (word_id, position, gloss_es, example_en, "
                    "example_es, flags, created_at) VALUES (?,2,?,?,?,?,?)",
                    (row["id"], second["gloss_es"].strip(), second["example_en"].strip(),
                     second["example_es"].strip(), reasons, ts))
        proposed += 1
    return {"proposed": proposed, "skipped": skipped}


def queue(conn: sqlite3.Connection) -> dict:
    """Propuestas pendientes junto al contexto original de cada tarjeta."""
    rows = conn.execute(
        "SELECT s.id, s.word_id, w.word, w.meaning_es AS current_gloss, "
        "w.example_en, w.example_es, s.flags, s.pos, s.gloss_es, "
        "s.definition_en, s.note_es, s.imageable FROM senses s "
        "JOIN words w ON w.id=s.word_id "
        "WHERE s.position=1 AND s.status='proposed' ORDER BY s.id").fetchall()
    proposed = []
    for row in rows:
        item = dict(row)
        item["flags"] = json.loads(item["flags"] or "[]")
        item["imageable"] = bool(item["imageable"])
        second = conn.execute(
            "SELECT gloss_es, example_en, example_es FROM senses "
            "WHERE word_id=? AND position=2 AND status='proposed' ORDER BY id LIMIT 1",
            (row["word_id"],)).fetchone()
        item["second"] = dict(second) if second else None
        proposed.append(item)
    return {"candidates": len(candidates(conn)), "proposed": proposed}


class SenseNotFound(ValueError):
    """Permite distinguir un id inexistente de una transición inválida."""


def decide(conn: sqlite3.Connection, sense_id: int, action: str,
           gloss_es: "str | None" = None, definition_en: "str | None" = None) -> dict:
    """Decide la acepción principal y su hermana en una sola transacción."""
    with conn:
        # Leer bajo el candado impide dos aceptaciones con la misma copia vieja.
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        sense = conn.execute("SELECT * FROM senses WHERE id=?", (sense_id,)).fetchone()
        if sense is None:
            raise SenseNotFound("acepción no encontrada")
        if sense["position"] != 1:
            raise ValueError("sólo se decide la acepción principal")
        if action not in ("accept", "reject", "revert"):
            raise ValueError("acción desconocida")
        expected = "accepted" if action == "revert" else "proposed"
        if sense["status"] != expected:
            raise ValueError(f"no se puede {action} una acepción {sense['status']}")
        word = conn.execute("SELECT * FROM words WHERE id=?", (sense["word_id"],)).fetchone()
        ts = db.now_iso()
        if action == "accept":
            gloss = sense["gloss_es"] if gloss_es is None else gloss_es.strip()
            definition = sense["definition_en"] if definition_en is None else definition_en.strip()
            if gloss_es is not None:
                why = _gloss_problem(gloss)
                if why:
                    raise ValueError(why)
            if definition_en is not None:
                why = glossary.problem(definition, word["word"])
                if why:
                    raise ValueError(f"definition_en: {why}")
            conn.execute(
                "UPDATE senses SET gloss_es=?, definition_en=?, old_meaning_es=?, "
                "old_meaning_en=? WHERE id=?",
                (gloss, definition, word["meaning_es"], word["meaning_en"], sense_id))
            conn.execute(
                "UPDATE words SET meaning_es=?, meaning_en=?, updated_at=? WHERE id=?",
                (gloss, definition or word["meaning_en"], ts, word["id"]))
        elif action == "revert":
            conn.execute(
                "UPDATE words SET meaning_es=?, meaning_en=?, updated_at=? WHERE id=?",
                (sense["old_meaning_es"], sense["old_meaning_en"], ts, word["id"]))
        status = "accepted" if action == "accept" else "rejected"
        conn.execute(
            "UPDATE senses SET status=?, decided_at=? WHERE id=? "
            "OR (word_id=? AND position=2)",
            (status, ts, sense_id, word["id"]))
    return {"id": sense_id, "word_id": word["id"], "status": status}
