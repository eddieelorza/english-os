"""Deja listo el material del día tras una sesión real de Anki (ADR-008 D5).

Lo lanza `run_all.py session-end` al final. Corre en este proceso, así que la
generación es naturalmente serializada: una inferencia a la vez, cuando Eddie
ya cerró Anki y no está esperando nada.

No es fatal: si el modelo local no está disponible o falla, el día sigue
funcionando y el material se puede pedir a mano.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app import db, jobs  # noqa: E402


def main() -> int:
    conn = db.connect()
    try:
        jobs.requeue_orphans(conn)
        result = jobs.pregenerate(conn)
        if result.get("skipped"):
            print(f"⏭  pregenerate: {result['skipped']} — nada que preparar.")
            return 0
        failed = result.get("failed") or []
        print(f"📝 Material listo: {result['processed']} trabajo(s)"
              + (f", {len(failed)} fallido(s)" if failed else ""))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
