"""Práctica productiva: corrección determinista y scheduling independiente."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone

from fsrs import Card, Rating, State

from app import db, deck, experiments, glossary, srs

NEW_PER_DAY = 5
MIN_RECEPTIVE_STABILITY = 7

_ELIGIBLE = """
    w.card_state='REVIEW' AND w.stability >= ?
    AND trim(COALESCE(w.meaning_es, '')) != ''
    AND trim(COALESCE(w.example_en, '')) != ''
    AND NOT EXISTS (
        SELECT 1 FROM cards c WHERE c.word_id=w.id AND c.track='productive'
    )
    AND NOT EXISTS (
        SELECT 1 FROM experiment_arms e
        WHERE e.word_id=w.id AND e.experiment='E2' AND e.arm='control'
    )
"""


def _matches(word: str, sentence: str):
    """Localiza formas conservando los índices del texto original."""
    word = word.strip()
    if not word:
        return []
    if len(word.split()) > 1:
        pattern = r"(?<!\w)" + re.escape(word) + r"(?!\w)"
        return list(re.finditer(pattern, sentence, re.IGNORECASE))
    stem = glossary._fold(word[:max(3, len(word) - 2)])
    return [m for m in re.finditer(r"[^\W\d_]+", sentence)
            if stem and glossary._fold(m.group()).startswith(stem)]


def surface(word: str, sentence: str) -> str | None:
    """Devuelve la primera forma del lema en el ejemplo, sin lematizador."""
    matches = _matches(word, sentence or "")
    return matches[0].group() if matches else None


def _normalize(value: str) -> str:
    """Pliega acentos y caja sin perder espacios ni puntuación interna."""
    value = " ".join(value.split())
    while value and unicodedata.category(value[0]).startswith("P"):
        value = value[1:].lstrip()
    while value and unicodedata.category(value[-1]).startswith("P"):
        value = value[:-1].rstrip()
    return "".join(c for c in unicodedata.normalize("NFD", value.casefold())
                   if unicodedata.category(c) != "Mn")


def _distance(left: str, right: str) -> int:
    """Distancia de Levenshtein con una fila de memoria."""
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def grade(expected: str, given: str, lemma: str | None = None) -> tuple[str, int]:
    """Califica la forma esperada; el lema de un cloze merece Hard."""
    expected, given = _normalize(expected), _normalize(given)
    if not given:
        return "wrong", 1
    if given == expected:
        return "correct", 3
    if lemma is not None and given == _normalize(lemma) != expected:
        return "close", 2
    if (sum(c.isalpha() for c in expected) >= 4
            and _distance(expected, given) <= (1 if len(expected) <= 7 else 2)):
        return "close", 2
    return "wrong", 1


def choose(available, stability, last_wrong, recent, reps=0) -> str:
    """Prioriza apoyo, luego producción; evita tres ejercicios iguales."""
    if reps == 0 or stability is None or stability < 3 or last_wrong:
        order = ("cloze", "meaning", "image")
    elif reps % 3 == 0:
        order = ("image", "meaning", "cloze")
    else:
        order = ("meaning", "cloze", "image")
    choices = [kind for kind in order if kind in available]
    if not choices:
        raise ValueError("No hay ejercicios disponibles")
    if len(recent) >= 2 and recent[0] == recent[1] and len(choices) > 1:
        choices = [kind for kind in choices if kind != recent[0]]
    return choices[0]


def _available(conn, word):
    sense = conn.execute(
        "SELECT pos, imageable FROM senses WHERE word_id=? "
        "AND position=1 AND status='accepted' ORDER BY imageable DESC, id DESC LIMIT 1",
        (word["id"],)).fetchone()
    available = {"meaning"}
    if surface(word["word"], word["example_en"]):
        available.add("cloze")
    if word["image_path"] and sense and sense["imageable"] == 1:
        available.add("image")
    return available, sense


def _new_left(conn, now: datetime) -> int:
    # created_at y el historial usan reloj local; sólo due es UTC.
    day = db.study_day(now.astimezone().replace(tzinfo=None))
    start = db.study_day_start(day)
    end = (datetime.fromisoformat(start) + timedelta(days=1)).isoformat(
        timespec="seconds")
    count = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE track='productive' "
        "AND created_at >= ? AND created_at < ?", (start, end)).fetchone()[0]
    return max(0, NEW_PER_DAY - count)


def _item(conn, word, card) -> dict:
    available, sense = _available(conn, word)
    # La variedad se mide en la sesión (los dos últimos servidos, de cualquier
    # palabra); el escalón hacia abajo, en la última respuesta de ESTA card.
    recent = [r[0] for r in conn.execute(
        "SELECT exercise FROM recall_log ORDER BY reviewed_at DESC, id DESC LIMIT 2")]
    last = conn.execute(
        "SELECT verdict FROM recall_log WHERE card_id=? "
        "ORDER BY reviewed_at DESC, id DESC LIMIT 1",
        (card["id"],)).fetchone() if card else None
    exercise = choose(available, card["stability"] if card else None,
                      bool(last and last["verdict"] == "wrong"), recent,
                      reps=card["reps"] if card else 0)
    item = {"word_id": word["id"], "card_id": card["id"] if card else None,
            "exercise": exercise, "meaning_es": word["meaning_es"],
            "definition_en": word["meaning_en"] or None, "is_new": card is None}
    if sense and sense["pos"]:
        item["pos"] = sense["pos"]
    if exercise == "cloze":
        matches = _matches(word["word"], word["example_en"])
        expected = matches[0].group()
        sentence = word["example_en"]
        # Oculta todas las apariciones: otra mención regalaría la respuesta.
        for match in reversed(matches):
            sentence = sentence[:match.start()] + "____" + sentence[match.end():]
        item.update(sentence=sentence,
                    hint=f"{expected[0].lower()}·{sum(c.isalpha() for c in expected)}",
                    translation=word["example_es"])
    elif exercise == "image":
        item["image"] = word["image_path"]
    return item


def next_item(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """Sirve la más vencida o una nueva dentro del cupo del día de estudio."""
    now = (now or db.now_utc()).astimezone(timezone.utc)
    due = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE track='productive' AND due<=?",
        (now.isoformat(),)).fetchone()[0]
    new_left = _new_left(conn, now)
    card = conn.execute(
        "SELECT * FROM cards WHERE track='productive' AND due<=? "
        "ORDER BY due, id LIMIT 1", (now.isoformat(),)).fetchone()
    word = None
    if card:
        word = conn.execute("SELECT * FROM words WHERE id=?",
                            (card["word_id"],)).fetchone()
    elif new_left:
        # E2: cada palabra se asigna al introducirla; las de control se quedan
        # sólo con Review y se busca la siguiente.
        while True:
            word = conn.execute(
                f"SELECT w.* FROM words w WHERE {_ELIGIBLE} "
                "ORDER BY w.stability DESC, w.id LIMIT 1",
                (MIN_RECEPTIVE_STABILITY,)).fetchone()
            if word is None or experiments.arm(conn, "E2", word["id"]) == "recall":
                break
        conn.commit()
    return {"item": _item(conn, word, card) if word else None,
            "due": due, "new_left": new_left}


def answer(conn: sqlite3.Connection, word_id: int, exercise: str, given: str,
           now: datetime | None = None) -> dict:
    """Reconstruye la solución y guarda card e historial en una transacción."""
    now = (now or db.now_utc()).astimezone(timezone.utc)
    reviewed_at = now.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
    with conn:
        # El cupo y la creación se deciden bajo el mismo bloqueo de escritura.
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        word = conn.execute("SELECT * FROM words WHERE id=?", (word_id,)).fetchone()
        if word is None:
            raise ValueError(f"Palabra {word_id} no encontrada")
        available, _ = _available(conn, word)
        if exercise not in available:
            raise ValueError(f"Ejercicio {exercise} no disponible para esta palabra")
        row = conn.execute(
            "SELECT * FROM cards WHERE word_id=? AND track='productive'",
            (word_id,)).fetchone()
        if row is None:
            eligible = conn.execute(
                f"SELECT 1 FROM words w WHERE w.id=? AND {_ELIGIBLE}",
                (word_id, MIN_RECEPTIVE_STABILITY)).fetchone()
            if not eligible:
                raise ValueError("La palabra todavía no es elegible para Recall")
            if not _new_left(conn, now):
                raise ValueError("Se agotó el cupo de palabras nuevas de Recall")
        expected = (surface(word["word"], word["example_en"])
                    if exercise == "cloze" else word["word"])
        verdict, rating = grade(expected, given,
                                lemma=word["word"] if exercise == "cloze" else None)
        card = Card.from_json(row["fsrs_card"]) if row else Card()
        stability_before = card.stability
        lapsed = bool(row and card.state == State.Review and rating == 1)
        card, _ = srs._scheduler(conn).review_card(card, Rating(rating), now)
        if row is None:
            card_id = conn.execute(
                "INSERT INTO cards(word_id, fsrs_card, due, stability, difficulty, "
                "reps, created_at) VALUES(?, ?, ?, ?, ?, 1, ?)",
                (word_id, card.to_json(), card.due.isoformat(), card.stability,
                 card.difficulty, reviewed_at)).lastrowid
        else:
            card_id = row["id"]
            conn.execute(
                "UPDATE cards SET fsrs_card=?, due=?, stability=?, difficulty=?, "
                "reps=reps+1, lapses=lapses+? WHERE id=?",
                (card.to_json(), card.due.isoformat(), card.stability,
                 card.difficulty, int(lapsed), card_id))
        conn.execute(
            "INSERT INTO recall_log(card_id, word_id, reviewed_at, exercise, "
            "expected, answer, verdict, rating, stability_before, stability_after) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (card_id, word_id, reviewed_at, exercise, expected, given, verdict,
             rating, stability_before, card.stability))
        new_left = _new_left(conn, now)
        due = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE track='productive' AND due<=?",
            (now.isoformat(),)).fetchone()[0]
    seconds = max(0.0, (card.due - now).total_seconds())
    return {"verdict": verdict, "rating": rating, "expected": expected,
            "word": word["word"], "given": given, "example_en": word["example_en"],
            "example_es": word["example_es"], "meaning_es": word["meaning_es"],
            # Sólo palabras concretas: en las abstractas la imagen engaña.
            "image": word["image_path"] if "image" in available else None,
            "audio": word["audio_word"],
            "interval_days": max(0.0, round(seconds / 86400, 4)),
            "interval": deck.human_delta(seconds),
            "due": due, "new_left": new_left}
