"""La compuerta de palabras nuevas (ADR-014 D3).

`new_per_day` era una cifra fija: 10 al día entraban igual con 100 repasos
vencidos, tras nueve días fuera, o con las últimas palabras pegándose la mitad
de las veces. Medido el 2026-09-20: recall 92-98% en cards con estabilidad de
2 días o más, 71% por debajo, y 45% en los pasos de aprendizaje — el 44% de
todos los repasos eran esa noria. El mazo maduro estaba sano; lo que no se
aprendía era lo recién metido, y cada día se metía más.

Aquí `new_per_day` pasa a ser el TECHO. Cuántas entran hoy lo deciden, en
este orden:

1. **Palabras volviendo.** Mientras el triage tenga perdidas en goteo, ellas
   son las nuevas.
2. **Hueco.** Lo vencido va antes: si ya llena el día, no entra nada.
3. **La escalera.** Demasiadas a medio aprender: primero se terminan ésas.
4. **Cómo se están pegando.** El recall de las cards jóvenes fija el ritmo.

Siempre devuelve el porqué, en inglés (copy de UI): una compuerta que recorta
callada es el mismo defecto que "pedías 6 y te daba 5".
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

# Una card es "joven" mientras su estabilidad no llegue a una semana: ahí es
# donde está la diferencia entre 71% y 92%.
YOUNG_STABILITY_DAYS = 7.0
YOUNG_WINDOW_DAYS = 14
MIN_YOUNG_REVIEWS = 20
# (recall mínimo, nuevas al día). Por debajo del primero, ninguna.
RAMP = ((0.85, None), (0.80, 5), (0.70, 3))
# Cards en LEARNING/RELEARNING a partir de las cuales no se abren más frentes.
LADDER_MAX = 8


def young_recall(conn: sqlite3.Connection,
                 window_days: int = YOUNG_WINDOW_DAYS) -> dict:
    """¿Se están quedando las palabras recientes? Aciertos en repasos de
    cards con poca estabilidad. Los pasos de aprendizaje no cuentan: fallar
    al minuto de ver una palabra es parte de aprenderla, no un olvido."""
    since = (datetime.now() - timedelta(days=window_days)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS n, SUM(CASE WHEN rating > 1 THEN 1 ELSE 0 END) AS ok "
        "FROM review_history WHERE source='fsrs' AND review_kind='review' "
        "AND stability_before IS NOT NULL AND stability_before < ? "
        "AND reviewed_at >= ?", (YOUNG_STABILITY_DAYS, since)).fetchone()
    n = row["n"] or 0
    enough = n >= MIN_YOUNG_REVIEWS
    return {"value": round((row["ok"] or 0) / n, 3) if enough else None,
            "reviews": n, "enough": enough, "window_days": window_days}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def allowed(conn: sqlite3.Connection, capacity: "int | None" = None,
            mode: "str | None" = None) -> dict:
    """Cuántas palabras nuevas admite hoy, y por qué."""
    from app import backlog, session

    cfg = session.settings(conn)
    ceiling = cfg["new_per_day"]
    mode = mode or cfg["mode"]

    def answer(n: int, code: str, reason: "str | None" = None) -> dict:
        n = max(0, min(n, ceiling))
        return {"new_per_day": n, "ceiling": ceiling, "code": code,
                # sólo hay "porqué" si de verdad se recortó algo
                "reason": reason if n < ceiling else None}

    if cfg["new_gate"] == "off" or ceiling <= 0:
        return answer(ceiling, "off")

    coming_back = conn.execute(
        "SELECT COUNT(*) FROM words WHERE comeback_on IS NOT NULL").fetchone()[0]
    if coming_back:
        return answer(0, "comeback",
                      f"new words on hold — {_plural(coming_back, 'word')} you "
                      f"had lost {'is' if coming_back == 1 else 'are'} coming "
                      f"back first")

    # ADR-015: en modo auto el grupo de palabras sin consolidar manda sobre el
    # resto. Una entra por cada una que se asentó.
    group_rule = None
    if mode == "auto":
        from app import load
        group_rule = load.new_allowed(conn, ceiling)
        if group_rule["new"] == 0:
            return answer(0, "group", group_rule["reason"])

    cap = backlog.capacity(conn) if capacity is None else max(0, capacity)
    due = backlog.due_total(conn)
    # En modo manual las nuevas y los repasos se piden por separado: no hay un
    # cupo común del que descontar, sólo la pregunta de si lo vencido cabe.
    room = cap - due if mode in ("time", "auto") else (ceiling if due <= cap else 0)
    if room <= 0:
        return answer(0, "full",
                      "new words on hold — what is already due fills today")

    ladder = conn.execute(
        "SELECT COUNT(*) FROM words "
        "WHERE card_state IN ('LEARNING','RELEARNING')").fetchone()[0]
    if ladder >= LADDER_MAX:
        return answer(0, "ladder",
                      f"new words on hold — {_plural(ladder, 'word')} still "
                      f"being learned")

    def fitted(n: int, code: str, reason: str) -> dict:
        n = min(n, ceiling)
        if group_rule is not None and group_rule["new"] < n:
            return answer(group_rule["new"], "group", group_rule["reason"])
        if room < n:
            return answer(room, "room",
                          f"room for {_plural(room, 'new word')} — the rest of "
                          f"today is reviews")
        return answer(n, code, reason)

    recall = young_recall(conn)
    if not recall["enough"]:
        # Sin muestra no se afirma nada: la compuerta sólo frena con evidencia.
        return fitted(ceiling, "unmeasured", "")
    pct = round(recall["value"] * 100)
    for floor, per_day in RAMP:
        if recall["value"] >= floor:
            n = ceiling if per_day is None else per_day
            return fitted(n, "recall",
                          f"new words slowed to {n} a day — recent words are "
                          f"sticking {pct}% of the time")
    return answer(0, "recall",
                  f"new words on hold — recent words are sticking only {pct}% "
                  f"of the time")
