"""Línea base por habilidad (ADR-018, MVP 5): vocabulario sí/no y dictado.

Las dos pruebas se califican sin modelo. Los ítems son propios: palabras
reales repartidas en bandas de frecuencia **estimadas** (no medidas contra un
corpus) y fuera del mazo, pseudopalabras inventadas y comprobadas contra
/usr/share/dict/web2, y oraciones de dictado escritas para esta app. Por eso
el resultado es una banda aproximada con confianza baja, nunca un CEFR.

ponytail: una sola forma de cada prueba; las formas paralelas para el
check-in de 6 semanas se añaden cuando llegue la segunda toma.
"""

from __future__ import annotations

import json
import random
import re
import sqlite3

from app import db

# (banda, ancho de la banda en palabras, ítems). Bandas ~1k, 1-2k, 2-4k, 4-7k, 7-10k.
VOCAB_BANDS = [
    (1, 1000, "window kitchen angry cheap quiet wedding careful chair money teacher yellow ticket"),
    (2, 1000, "shelf rent rope envelope pillow fence crowd bottle pepper towel honest guilty"),
    (3, 2000, "sleeve sturdy plumber stain scrub nephew soak bucket rinse shrug squint whisk"),
    (4, 3000, "blister haggle smirk brittle wobble frugal chisel splinter lament mutter rustle quarry"),
    (5, 3000, "wheedle cajole truculent ewer quibble dross burnish skulk vellum cudgel wizened sedge"),
]
PSEUDO = ("plinder brastle flemmock drausion snorlet crimble throbe quenish mavely "
          "strubble lorrent fendle wimbert scrandle voddle chastomy blurten morkish "
          "sploven glonder").split()

# Corte aproximado de Milton (2010) sobre tamaño de vocabulario; orientativo.
VOCAB_CEFR = [(1500, "A1"), (2500, "A2"), (3250, "B1"), (3750, "B2"), (4500, "C1")]

DICTATION = [
    ("A2", "I usually take the bus to work in the morning."),
    ("A2", "Can you send me the file before lunch?"),
    ("B1", "We moved the meeting because half the team was on vacation."),
    ("B1", "If the build fails again, I'll check the logs tonight."),
    ("B2", "The client wasn't happy with the delay, but they agreed to a new deadline."),
    ("B2", "Nobody noticed the bug until it had already reached production."),
    ("C1", "Had we tested the migration earlier, we wouldn't have lost a whole afternoon."),
    ("C1", "The proposal sounds reasonable, although the costs are likely to be underestimated."),
    ("C2", "Whichever approach we settle on, it'll have to be rolled out gradually to avoid disrupting existing users."),
    ("C2", "She'd barely finished presenting when the questions started piling up from every corner of the room."),
]
DICTATION_PASS = 0.8   # un nivel se da por oído con ≥ 80% de palabras en sus dos oraciones


# ── Vocabulario ──────────────────────────────────────────────────────────

def vocab_items(seed: "int | None" = None) -> "list[str]":
    """Reales y pseudopalabras mezcladas; nada en la respuesta delata cuál es cuál."""
    words = [w for _, _, s in VOCAB_BANDS for w in s.split()] + PSEUDO
    random.Random(seed).shuffle(words)
    return words


def score_vocab(answers: "dict[str, bool]") -> dict:
    """Aciertos por banda corregidos por falsas alarmas: (h - f) / (1 - f)."""
    unknown = set(answers) - {w for _, _, s in VOCAB_BANDS for w in s.split()} - set(PSEUDO)
    if unknown:
        raise ValueError(f"Ítems desconocidos: {', '.join(sorted(unknown))}")
    missing = len(PSEUDO) + sum(len(s.split()) for _, _, s in VOCAB_BANDS) - len(answers)
    if missing:
        raise ValueError(f"Faltan {missing} respuestas.")
    f = sum(answers[p] for p in PSEUDO) / len(PSEUDO)
    bands, size = [], 0.0
    for band, width, items in VOCAB_BANDS:
        items = items.split()
        h = sum(answers[w] for w in items) / len(items)
        known = max(0.0, (h - f) / (1 - f)) if f < 1 else 0.0
        size += known * width
        bands.append({"band": band, "hits": round(h, 2), "known": round(known, 2)})
    size = int(round(size, -2))
    cefr = next((lvl for cut, lvl in VOCAB_CEFR if size < cut), "C2")
    # Muchas falsas alarmas = la estimación no se sostiene.
    confidence = "low" if f <= 0.1 else "very low"
    return {"size": size, "cefr": cefr, "false_alarms": round(f, 2),
            "bands": bands, "confidence": confidence}


# ── Dictado ──────────────────────────────────────────────────────────────

# "I'll" o "I will" es la misma palabra oída. 'd y 's se quedan: son ambiguas.
_CONTRACTIONS = [(r"\bwon't\b", "will not"), (r"\bcan't\b", "can not"), (r"\bcannot\b", "can not"),
                 (r"n't\b", " not"), (r"'ll\b", " will"), (r"'re\b", " are"),
                 (r"'ve\b", " have"), (r"\bi'm\b", "i am")]


def _tokens(text: str) -> "list[str]":
    text = text.lower().replace("’", "'")
    for pattern, full in _CONTRACTIONS:
        text = re.sub(pattern, full, text)
    return re.findall(r"[a-z0-9']+", text)


def _word_distance(a: "list[str]", b: "list[str]") -> int:
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def dictation_items() -> "list[dict]":
    """Audio a velocidad normal, del TTS local (en caché tras la primera vez)."""
    from app import tts
    return [{"id": i, "level": level, "audio": tts.narrate(text)["path"]}
            for i, (level, text) in enumerate(DICTATION)]


def score_dictation(responses: "list[str]") -> dict:
    if len(responses) != len(DICTATION):
        raise ValueError(f"Se esperaban {len(DICTATION)} respuestas.")
    items, by_level = [], {}
    for (level, text), given in zip(DICTATION, responses):
        ref = _tokens(text)
        acc = max(0.0, 1 - _word_distance(ref, _tokens(given)) / len(ref))
        items.append({"level": level, "expected": text, "given": given,
                      "accuracy": round(acc, 2)})
        by_level.setdefault(level, []).append(acc)
    levels = [{"level": lvl, "accuracy": round(sum(a) / len(a), 2)}
              for lvl, a in by_level.items()]
    band = "below A2"
    for lvl in levels:               # en orden: el primer nivel que falla corta
        if lvl["accuracy"] < DICTATION_PASS:
            break
        band = lvl["level"]
    overall = sum(i["accuracy"] for i in items) / len(items)
    return {"band": band, "accuracy": round(overall, 2), "levels": levels,
            "items": items, "confidence": "low"}


# ── Persistencia ─────────────────────────────────────────────────────────

def save(conn: sqlite3.Connection, kind: str, result: dict, answers) -> dict:
    conn.execute(
        "INSERT INTO assessments (kind, taken_at, result, answers) VALUES (?, ?, ?, ?)",
        (kind, db.now_iso(), json.dumps(result, ensure_ascii=False),
         json.dumps(answers, ensure_ascii=False)))
    conn.commit()
    return result


def latest(conn: sqlite3.Connection) -> dict:
    out = {}
    for kind in ("vocab", "dictation"):
        row = conn.execute(
            "SELECT taken_at, result FROM assessments WHERE kind = ? "
            "ORDER BY taken_at DESC, id DESC LIMIT 1", (kind,)).fetchone()
        out[kind] = ({"taken_at": row["taken_at"], **json.loads(row["result"])}
                     if row else None)
    return out


if __name__ == "__main__":
    yes = {w: True for w in vocab_items()}
    assert score_vocab({**yes, **{p: False for p in PSEUDO}})["size"] == 10000
    assert score_dictation([t for _, t in DICTATION])["band"] == "C2"
    print("ok")
