"""Notion block builders and property readers.

Single place for the helpers that were duplicated across writing_session_daily,
reading_page_daily, and anki_notion_sync.
"""

from __future__ import annotations

from typing import Iterable

RICH_TEXT_LIMIT = 2000  # Notion's hard limit per rich_text chunk.


# ── Rich text + property values ──────────────────────────────────────────

def rt(text: str | None, limit: int = RICH_TEXT_LIMIT) -> list[dict]:
    """Build a rich_text array, splitting long text into chunks of `limit`."""
    text = text or ""
    if not text:
        return []
    chunks = [text[i:i + limit] for i in range(0, len(text), limit)]
    return [{"type": "text", "text": {"content": c}} for c in chunks]


def title_prop(text: str | None) -> dict:
    """Property value for a title field."""
    return {"title": [{"text": {"content": (text or "")}}]}


def rich_text_prop(text: str | None) -> dict:
    """Property value for a rich_text field."""
    return {"rich_text": rt(text)}


def number_prop(value: float | int | None) -> dict:
    return {"number": (None if value is None else float(value))}


def date_prop(start: str, end: str | None = None) -> dict:
    body: dict = {"start": start}
    if end:
        body["end"] = end
    return {"date": body}


def select_prop(name: str | None) -> dict:
    return {"select": (None if not name else {"name": name})}


def checkbox_prop(value: bool) -> dict:
    return {"checkbox": bool(value)}


# ── Block builders ───────────────────────────────────────────────────────

def heading(text: str, level: int = 2) -> dict:
    if level not in (1, 2, 3):
        raise ValueError("heading level must be 1, 2 or 3")
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": rt(text)}}


def paragraph(text: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt(text)}}


def paragraph_blocks(text: str, limit: int = 1800) -> list[dict]:
    """Split long text into multiple paragraph blocks."""
    text = text or ""
    if not text:
        return [paragraph("")]
    parts = [text[i:i + limit] for i in range(0, len(text), limit)]
    return [paragraph(p) for p in parts]


def divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def callout(text: str, emoji: str = "📌") -> dict:
    return {
        "object": "block",
        "type": "callout",
        "callout": {"rich_text": rt(text), "icon": {"type": "emoji", "emoji": emoji}},
    }


def quote(text: str) -> dict:
    return {"object": "block", "type": "quote", "quote": {"rich_text": rt(text)}}


def todo(text: str, checked: bool = False) -> dict:
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {"rich_text": rt(text), "checked": bool(checked)},
    }


def todo_list(items: Iterable[str]) -> list[dict]:
    return [todo(x) for x in items]


def table_row(cells: list[list[dict]]) -> dict:
    """A single table row. `cells` is a list of rich_text arrays (one per column)."""
    return {"object": "block", "type": "table_row", "table_row": {"cells": cells}}


def table(rows: list[list[str]], headers: list[str] | None = None) -> dict:
    """Build a table block from string rows. `headers` enables the column header row."""
    has_header = headers is not None
    width = len(headers) if has_header else (len(rows[0]) if rows else 0)

    children = []
    if has_header:
        children.append(table_row([rt(h) for h in headers]))
    for r in rows:
        children.append(table_row([rt(c) for c in r]))

    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": has_header,
            "has_row_header": False,
            "children": children,
        },
    }


# ── Property readers ──────────────────────────────────────────────────────

def get_title(props: dict, name: str) -> str:
    p = props.get(name, {})
    if p.get("type") != "title":
        return ""
    return "".join(x.get("plain_text", "") for x in p.get("title", []))


def get_rich_text(props: dict, name: str) -> str:
    p = props.get(name, {})
    if p.get("type") != "rich_text":
        return ""
    return "".join(x.get("plain_text", "") for x in p.get("rich_text", []))


def get_number(props: dict, name: str) -> float | None:
    p = props.get(name, {})
    if p.get("type") != "number":
        return None
    return p.get("number")


def get_checkbox(props: dict, name: str) -> bool:
    p = props.get(name, {})
    if p.get("type") != "checkbox":
        return False
    return bool(p.get("checkbox"))


def get_select(props: dict, name: str) -> str | None:
    p = props.get(name, {})
    if p.get("type") != "select":
        return None
    sel = p.get("select")
    return sel.get("name") if sel else None


def get_date(props: dict, name: str) -> str | None:
    p = props.get(name, {})
    if p.get("type") != "date":
        return None
    d = p.get("date")
    return d.get("start") if d else None


# ── Block content readers ────────────────────────────────────────────────

def block_plain_text(block: dict) -> str:
    """Best-effort text extraction from any block that carries rich_text."""
    btype = block.get("type")
    if not btype:
        return ""
    body = block.get(btype, {})
    rich = body.get("rich_text") or body.get("cells") or []
    if isinstance(rich, list) and rich and isinstance(rich[0], dict):
        return "".join(x.get("plain_text", "") for x in rich)
    return ""
