"""Normaliza categorías existentes; sólo escribe si se pasa --apply."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app.speaking import normalize_category  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", nargs="?", default="data/english.db")
    parser.add_argument("--apply", action="store_true",
                        help="aplica los cambios en una sola transacción")
    args = parser.parse_args()
    # El ensayo abre en sólo lectura y nunca crea una base por accidente.
    uri = Path(args.database).resolve().as_uri()
    conn = sqlite3.connect(uri + ("?mode=rw" if args.apply else "?mode=ro"),
                           uri=True)
    try:
        with conn:
            rows = conn.execute(
                "SELECT category, COUNT(*) FROM errors GROUP BY category "
                "ORDER BY category").fetchall()
            print("old category → new category → rows")
            unknown = []
            for old, count in rows:
                new = normalize_category(old)
                print(f"{old} → {new if new is not None else '(sin normalizar)'} → {count}")
                if new is None:
                    unknown.append(old)
                elif args.apply and old != new:
                    conn.execute("UPDATE errors SET category=? WHERE category=?",
                                 (new, old))
            print("Categorías desconocidas: " +
                  (", ".join(str(c) for c in unknown) if unknown else "ninguna"))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
