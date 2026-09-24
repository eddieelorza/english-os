"""Definiciones en inglés para el reverso de la tarjeta.

Por qué existe: el 100% de las tarjetas tenía `meaning_en` vacío, así que el
reverso era una palabra en español y nada más. Para un cognado eso basta
(`province` → "Provincia" se lee solo). Para un no-cognado es memorizar un par
sin asidero, y ahí es donde se atascan: medido sobre su propio mazo, las
palabras que **no** se parecen a su traducción tienen dificultad media 5.8 e
intervalo mediano de 16 días, contra 3.1 y 32 días de los cognados.

Una definición en inglés da una segunda vía al significado que no pasa por el
español. Es una apuesta, y se mide: la lista de atascadas tiene que encoger.

Lo que este módulo NO hace: mnemotecnias. Se probaron con el modelo local y
salieron incoherentes ("SHED suena como 'sed', y tu sed puede aliviar la sed
de querer un cobertizo"). Definir se le da bien; inventar ganchos, no.
"""

from __future__ import annotations

import sqlite3
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import ai, db  # noqa: E402

SYSTEM = """Eres un tutor de inglés. Defines palabras para un hispanohablante
de nivel B1 que ya conoce la traducción y necesita una segunda vía al
significado.

Devuelves una definición EN INGLÉS de 6 a 14 palabras, en nivel A2-B1.
Una definición, no un sinónimo: "explosion" no define `burst`; "a sudden
breaking open with force" sí.

Reglas duras:
- NUNCA uses la palabra definida (ni una forma derivada) dentro de la
  definición.
- La definición debe encajar con el SENTIDO del ejemplo que te doy, no con
  otra acepción de la palabra.
- Empieza con el patrón del tipo de palabra: "to ..." para un verbo, "a ..."
  o "the ..." para un sustantivo, un adjetivo directamente.
- Nada de español. Nada de comillas. Una sola frase, sin punto final.
"""

SCHEMA = {"type": "object",
          "properties": {"definition": {"type": "string"}},
          "required": ["definition"]}


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn" and c.isalpha())


def cognate_score(word: str, meaning_es: str) -> float:
    """Cuánto se parece la palabra inglesa a su traducción (0-1).

    Proxy barato de "cognado" y, medido, el mejor predictor que hay en esta
    base de si una palabra se queda: mejor que el número de repasos, el mazo
    o los lapses. Se compara contra cada palabra del glosario porque las
    traducciones vienen en frase ("Morir De Hambre").
    """
    best = 0.0
    for token in (meaning_es or "").split():
        best = max(best, SequenceMatcher(None, _fold(word), _fold(token)).ratio())
    return best


# 3 y no 5: hay definiciones buenas y cortas ("to fail to notice"). Lo que
# se rechaza es el sinónimo suelto de una o dos palabras ("beneath", "to
# decay"), que no abre una segunda vía al significado.
MIN_WORDS, MAX_WORDS = 3, 16

# El reverso de una tarjeta es texto en inglés y nada más. El modelo local
# devolvió una vez `"a statement expressing不满，我no debo responder en
# chino...}],` — con caracteres chinos Y restos del JSON. Pasó todas las demás
# reglas (bastantes palabras, sin repetir el término) y habría acabado en una
# tarjeta real.
_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
               "0123456789 ,;:'’-()/&.")


def problem(definition: str, word: str) -> "str | None":
    """Qué le pasa a esta definición, o None si sirve.

    Cada regla vino de un fallo real del modelo local, no de la imaginación:

    - *circular*: usar la propia palabra ("to sew cloth with thread"). Es un
      chivatazo — el reverso regala el frente.
    - *sinónimo suelto*: "explosion" para `burst`, "beneath" para
      `underneath`. No abre una segunda vía al significado; sólo cambia una
      palabra que no sabes por otra.
    - *no es una definición*: "mixed things" para `stir` — un trozo de frase
      en pasado.
    - *a/an*: "a expression" para `complaint`. Un error de artículo en la
      cara del reverso enseña mal justo lo que se quiere enseñar.
    """
    d = (definition or "").strip()
    if not d:
        return "vacía"
    words = d.split()
    if len(words) < MIN_WORDS:
        return f"demasiado corta ({len(words)} palabras)"
    if len(words) > MAX_WORDS or len(d) > 140:
        return "demasiado larga"
    stem = _fold(word)[:max(4, len(word) - 2)]
    if stem in _fold(d):
        return "usa la propia palabra"
    strange = {ch for ch in d if ch not in _ALLOWED}
    if strange:
        return f"caracteres no ingleses: {''.join(sorted(strange))[:12]!r}"
    if len(words) > 1 and words[0].lower() == "a" and words[1][:1].lower() in "aeiou":
        return "artículo mal ('a' antes de vocal)"
    return None


def _valid(definition: str, word: str) -> bool:
    return problem(definition, word) is None


def pending(conn: sqlite3.Connection, only: "list[str] | None" = None) -> list:
    rows = conn.execute(
        "SELECT id, word, meaning_es, example_en FROM words "
        "WHERE meaning_en IS NULL AND meaning_es IS NOT NULL "
        "  AND example_en IS NOT NULL AND fsrs_card IS NOT NULL").fetchall()
    if only is not None:
        keep = {w.lower() for w in only}
        rows = [r for r in rows if r["word"].lower() in keep]
    # Primero las que menos se parecen a su traducción: son las que peor lo
    # tienen y donde la definición más puede aportar.
    return sorted(rows, key=lambda r: cognate_score(r["word"], r["meaning_es"]))


def fill(conn: sqlite3.Connection, only: "list[str] | None" = None,
         limit: "int | None" = None) -> dict:
    """Rellena `meaning_en`. Idempotente: sólo toca las que están vacías."""
    provider = ai.get_provider("glossary")
    done, rejected = [], []
    for row in pending(conn, only)[:limit]:
        definition, why = None, None
        # Se reintenta diciéndole QUÉ falló. Un reintento ciego con el mismo
        # prompt devuelve casi siempre lo mismo.
        for attempt in range(3):
            extra = ("" if attempt == 0 else
                     f"\n\nTu intento anterior fue rechazado ({why}): "
                     f'"{definition}". Corrígelo.')
            try:
                result = provider.generate_json(
                    SYSTEM,
                    f'Palabra: "{row["word"]}"\n'
                    f'Traducción al español: {row["meaning_es"]}\n'
                    f'Ejemplo (usa ESTE sentido): {row["example_en"]}{extra}',
                    SCHEMA)
            except Exception as exc:  # noqa: BLE001 — una palabra no tumba el lote
                why, definition = f"error: {exc}", None
                break
            definition = (result.get("definition") or "").strip().rstrip(".")
            why = problem(definition, row["word"])
            if why is None:
                break
        if why is not None:
            rejected.append((row["word"], f"{why}: {definition!r}"))
            continue
        conn.execute("UPDATE words SET meaning_en=?, updated_at=? WHERE id=?",
                     (definition, db.now_iso(), row["id"]))
        done.append((row["word"], definition))
    conn.commit()
    return {"filled": len(done), "rejected": len(rejected),
            "words": done, "problems": rejected}
