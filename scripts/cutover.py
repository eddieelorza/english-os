"""Cut-over de Anki: la app pasa a ser la única verdad (ADR-011).

    python3 scripts/cutover.py check     # comprobaciones, no toca nada
    python3 scripts/cutover.py run       # corta (exige que check pase)
    python3 scripts/cutover.py status
    python3 scripts/cutover.py revert    # vuelve al modo anterior

No modifica Anki en ningún caso: el mazo queda intacto, congelado como
archivo.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app import cutover, db  # noqa: E402

TICK = {True: "✓", False: "✗"}


def _show_preflight(pre: dict) -> None:
    for c in pre["checks"]:
        print(f"  {TICK[c['ok']]} {c['name']:24} {c['detail']}")
    if not pre["ok"]:
        print("\n  No es seguro cortar todavía.")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    conn = db.connect()
    try:
        if cmd == "check":
            print("Comprobaciones previas al cut-over:\n")
            pre = cutover.preflight(conn)
            _show_preflight(pre)
            return 0 if pre["ok"] else 1

        if cmd == "run":
            if cutover.done(conn):
                print(f"Ya estaba cortado el {cutover.state(conn)['date']}.")
                return 0
            print("Comprobaciones previas:\n")
            r = cutover.run(conn, force="--force" in sys.argv)
            _show_preflight(r["preflight"])
            if not r["cut_over"]:
                print("\n  Cancelado. Usa --force sólo si sabes lo que pierdes.")
                return 1
            snap = r.get("anki_snapshot") or {}
            print(f"\n  Cortado el {r['date']}.")
            print(f"  Anki queda congelado: {snap.get('cards', '?')} cards, "
                  f"{snap.get('by_type', {})}")
            print("  El mazo NO se ha tocado. Para volver atrás: "
                  "scripts/cutover.py revert")
            return 0

        if cmd == "revert":
            r = cutover.revert(conn)
            print("Revertido: el pipeline vuelve a leer de Anki."
                  if r["reverted"] else f"Nada que revertir ({r['reason']}).")
            return 0

        st = cutover.state(conn)
        if not st["cut_over"]:
            print("Sin cortar: Anki sigue siendo la fuente del scheduling.")
            return 0
        snap = st["anki_snapshot"] or {}
        print(f"Cortado el {st['date']}. La app es la única verdad.")
        print(f"Anki congelado con {snap.get('cards', '?')} cards: "
              f"{snap.get('by_type', {})}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
