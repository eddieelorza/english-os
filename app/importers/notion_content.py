"""Rescate del contenido de las páginas de Notion (ADR-012).

El importador de Notion (`importers/notion.py`) solo lee **propiedades**:
título, fecha, checkboxes. Nunca llamó a `get_block_children`. Resultado: en
la app los 77 writings y 79 de 86 readings tenían el cuerpo **vacío** — eran
cascarones. El inglés que Eddie escribió, las correcciones y las historias
generadas vivían únicamente dentro de Notion.

Apagar Notion sin esto habría borrado meses de trabajo sin que nadie se diera
cuenta hasta ir a buscarlo.

Qué hace: baja los bloques de cada página y guarda **la página entera** como
texto en `texts.body`, y aparte la sección de corrección en `texts.correction`.
Se guarda todo, no solo lo que hoy parece valioso: no es momento de decidir
qué merece sobrevivir.

Idempotente: solo toca filas con el cuerpo vacío, salvo `refresh=True`.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))

from app import db  # noqa: E402

# El encabezado que la routine de corrección escribe al final de la página.
CORRECTION_MARK = "corrección"
# Marcas de la historia en una página de Reading, y el placeholder que dejaba
# el pipeline cuando todavía no se había generado.
STORY_MARK = "story"
PLACEHOLDER_HINTS = ("generando tu historia", "⏳")

# Bloques cuyo texto no aporta nada al archivo.
SKIP_TYPES = {"divider", "table", "column_list", "column", "image"}


def _prefix(block_type: str) -> str:
    """Un poco de estructura para que el texto plano siga siendo legible."""
    return {
        "heading_1": "\n# ", "heading_2": "\n## ", "heading_3": "\n### ",
        "bulleted_list_item": "- ", "numbered_list_item": "- ",
        "to_do": "- ", "quote": "> ", "callout": "> ",
    }.get(block_type, "")


def page_text(client, page_id: str) -> "tuple[str, str | None]":
    """Devuelve (texto completo, corrección) de una página."""
    from notion_blocks import block_plain_text

    lines: "list[str]" = []
    correction: "list[str]" = []
    in_correction = False

    for block in client.get_block_children(page_id):
        btype = block.get("type", "")
        if btype in SKIP_TYPES:
            continue
        text = (block_plain_text(block) or "").strip()
        if not text:
            continue
        if btype.startswith("heading") and CORRECTION_MARK in text.lower():
            in_correction = True
        line = f"{_prefix(btype)}{text}"
        lines.append(line)
        if in_correction:
            correction.append(line)

    body = "\n".join(lines).strip()
    return body, ("\n".join(correction).strip() or None)


def _is_placeholder(body: str) -> bool:
    low = body.lower()
    return any(h in low for h in PLACEHOLDER_HINTS)


def run(conn: sqlite3.Connection, refresh: bool = False,
        limit: "int | None" = None) -> dict:
    """Baja el contenido de las páginas de Notion a `texts`."""
    from app import cutover
    from notion_client import NotionClient

    stats = {"scanned": 0, "filled": 0, "corrections": 0,
             "placeholders": 0, "failed": 0}
    if cutover.notion_done(conn) and not refresh:
        return {"skipped": "notion-off", **stats}

    where = "notion_page_id IS NOT NULL"
    if not refresh:
        where += " AND (body IS NULL OR TRIM(body) = '')"
    sql = (f"SELECT id, notion_page_id, kind, title FROM texts WHERE {where} "
           "ORDER BY date DESC")
    if limit:
        sql += f" LIMIT {int(limit)}"

    client = NotionClient()
    for row in conn.execute(sql).fetchall():
        stats["scanned"] += 1
        try:
            body, correction = page_text(client, row["notion_page_id"])
        except Exception as exc:  # noqa: BLE001 — una página rota no para el rescate
            print(f"  ! {row['title']}: {type(exc).__name__} {exc}")
            stats["failed"] += 1
            continue
        if not body:
            continue
        # Una historia sin generar no es contenido: guardarla como cuerpo haría
        # creer que la lectura existe.
        if row["kind"] == "reading" and _is_placeholder(body):
            stats["placeholders"] += 1
        sets, args = ["body=?"], [body]
        if correction:
            sets.append("correction=?")
            args.append(json.dumps({"source": "notion", "text": correction},
                                   ensure_ascii=False))
            stats["corrections"] += 1
        conn.execute(f"UPDATE texts SET {', '.join(sets)}, updated_at=? WHERE id=?",
                     args + [db.now_iso(), row["id"]])
        stats["filled"] += 1
    conn.commit()
    return stats


if __name__ == "__main__":
    conn = db.connect()
    try:
        print(run(conn, refresh="--refresh" in sys.argv))
    finally:
        conn.close()
