"""Apagar Notion: la app deja de alimentarlo (ADR-012).

    python3 scripts/notion_off.py check     # comprobaciones, no toca nada
    python3 scripts/notion_off.py rescue    # baja el contenido de las páginas
    python3 scripts/notion_off.py off       # apaga (exige que check pase)
    python3 scripts/notion_off.py status
    python3 scripts/notion_off.py on        # vuelve a encenderlo

No borra nada en Notion: las páginas quedan intactas como archivo, y seguirán
siendo legibles. Lo que se corta es la escritura.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

for line in (BASE / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from app import cutover, db  # noqa: E402

TICK = {True: "✓", False: "✗"}


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    conn = db.connect()
    try:
        if cmd == "rescue":
            from app.importers import notion_content
            print("Bajando el contenido de las páginas de Notion…")
            print(" ", notion_content.run(
                conn, refresh="--refresh" in sys.argv))
            return 0

        if cmd in ("check", "off"):
            pre = cutover.notion_preflight(conn)
            print("Comprobaciones antes de apagar Notion:\n")
            for c in pre["checks"]:
                print(f"  {TICK[c['ok']]} {c['name']:20} {c['detail']}")
            if cmd == "check":
                return 0 if pre["ok"] else 1
            if not pre["ok"] and "--force" not in sys.argv:
                print("\n  No es seguro apagar todavía. Corre primero:"
                      "\n    python3 scripts/notion_off.py rescue")
                return 1
            r = cutover.notion_off(conn, force="--force" in sys.argv)
            if r.get("already"):
                print(f"\n  Ya estaba apagado el {r['date']}.")
                return 0
            print(f"\n  Notion apagado el {r['date']}.")
            print("  Las páginas siguen ahí y se pueden leer; lo que se corta "
                  "es la escritura.")
            print("  Para volver: python3 scripts/notion_off.py on")
            return 0

        if cmd == "on":
            r = cutover.notion_on(conn)
            print("Notion encendido otra vez." if r["reverted"]
                  else f"Nada que hacer ({r['reason']}).")
            return 0

        st = cutover.notion_state(conn)
        if not st["notion_off"]:
            print("Notion sigue encendido: el pipeline le escribe.")
            return 0
        print(f"Notion apagado el {st['date']}. Archivo de solo lectura.")
        snap = st["snapshot"] or {}
        print(f"  contenido a salvo en la app: {snap.get('texts', {})}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
