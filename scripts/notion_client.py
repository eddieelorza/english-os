"""Shared Notion HTTP client with retry/backoff.

All scripts should go through NotionClient instead of raw requests calls.
Handles auth headers, pagination, 429 Retry-After, 5xx exponential backoff,
and network errors.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Iterator

import requests

log = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionError(Exception):
    """Raised when Notion returns a non-retryable error or retries are exhausted."""


class NotionOff(Exception):
    """Se intentó escribir en Notion después de apagarlo (ADR-012)."""


def _guard_write(method: str, path: str) -> None:
    """Un solo cerrojo para las seis rutas que escriben en Notion.

    Query de base de datos usa POST pero es lectura, así que se deja pasar.
    Las lecturas siguen funcionando a propósito: apagar Notion significa
    dejar de alimentarlo, no perder el acceso al archivo.
    """
    if method.upper() not in NotionClient._WRITE_METHODS:
        return
    if path.startswith("/databases/") and path.endswith("/query"):
        return
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from app import cutover, db as appdb
    except Exception:      # sin la app instalada no hay apagado que respetar
        return
    conn = appdb.connect()
    try:
        if cutover.notion_done(conn):
            since = cutover.notion_state(conn)["date"]
            raise NotionOff(
                f"Notion se apagó el {since} y algo intentó escribir "
                f"({method} {path}). Las páginas quedan como archivo. "
                f"Para volver: python3 scripts/notion_off.py on")
    finally:
        conn.close()


class NotionClient:
    _WRITE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}

    def __init__(self, token: str | None = None, max_retries: int = 5, timeout: int = 30):
        self.token = (token or os.environ.get("NOTION_TOKEN", "")).strip()
        if not self.token:
            raise NotionError("NOTION_TOKEN missing (set in .env)")
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        })

    def _request(self, method: str, path: str, **kwargs) -> dict:
        _guard_write(method, path)
        kwargs.setdefault("timeout", self.timeout)
        url = f"{NOTION_API}{path}"
        last_exc: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt == self.max_retries:
                    raise NotionError(
                        f"network error after {attempt} attempts on {method} {path}: {exc}"
                    ) from exc
                delay = min(2 ** (attempt - 1), 16)
                log.warning(
                    "network error on %s %s (attempt %d/%d): %s — sleeping %ds",
                    method, path, attempt, self.max_retries, exc, delay,
                )
                time.sleep(delay)
                continue

            if resp.status_code == 429:
                retry_after = self._parse_retry_after(resp, default=min(2 ** (attempt - 1), 16))
                log.warning(
                    "Notion 429 on %s %s — sleeping %ds (attempt %d/%d)",
                    method, path, retry_after, attempt, self.max_retries,
                )
                time.sleep(retry_after)
                continue

            if 500 <= resp.status_code < 600:
                if attempt == self.max_retries:
                    raise NotionError(
                        f"Notion {resp.status_code} after {attempt} attempts on {method} {path}: "
                        f"{resp.text[:200]}"
                    )
                delay = min(2 ** (attempt - 1), 16)
                log.warning(
                    "Notion %d on %s %s (attempt %d/%d) — sleeping %ds",
                    resp.status_code, method, path, attempt, self.max_retries, delay,
                )
                time.sleep(delay)
                continue

            if not resp.ok:
                raise NotionError(
                    f"Notion {resp.status_code} on {method} {path}: {resp.text[:300]}"
                )

            return resp.json() if resp.content else {}

        raise NotionError(
            f"unreachable: retries exhausted on {method} {path} ({last_exc})"
        )

    @staticmethod
    def _parse_retry_after(resp: requests.Response, default: int) -> int:
        raw = resp.headers.get("Retry-After")
        if not raw:
            return default
        try:
            return max(1, int(float(raw)))
        except (TypeError, ValueError):
            return default

    # ── Database queries ──────────────────────────────────────────────────

    def query_database(
        self,
        db_id: str,
        filter_obj: dict | None = None,
        sorts: list | None = None,
        page_size: int = 100,
    ) -> Iterator[dict]:
        """Yield every page matching the filter, auto-paginating."""
        body: dict[str, Any] = {"page_size": page_size}
        if filter_obj is not None:
            body["filter"] = filter_obj
        if sorts:
            body["sorts"] = sorts

        cursor: str | None = None
        while True:
            if cursor:
                body["start_cursor"] = cursor
            elif "start_cursor" in body:
                del body["start_cursor"]
            data = self._request("POST", f"/databases/{db_id}/query", json=body)
            yield from data.get("results", [])
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

    def find_first(self, db_id: str, filter_obj: dict) -> dict | None:
        for page in self.query_database(db_id, filter_obj, page_size=1):
            return page
        return None

    # ── Pages ─────────────────────────────────────────────────────────────

    def create_page(
        self,
        parent_db_id: str,
        properties: dict,
        children: list | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "parent": {"database_id": parent_db_id},
            "properties": properties,
        }
        if children:
            body["children"] = children
        return self._request("POST", "/pages", json=body)

    def update_page(self, page_id: str, properties: dict) -> dict:
        return self._request("PATCH", f"/pages/{page_id}", json={"properties": properties})

    # ── Blocks ────────────────────────────────────────────────────────────

    def get_block_children(self, block_id: str) -> list[dict]:
        """Return ALL children of a block/page, auto-paginating."""
        out: list[dict] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = self._request("GET", f"/blocks/{block_id}/children", params=params)
            out.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return out

    def append_block_children(
        self,
        block_id: str,
        blocks: list[dict],
        after: str | None = None,
    ) -> dict:
        """Append blocks as children. If `after` is given, insert immediately
        after that sibling block instead of at the end."""
        body: dict[str, Any] = {"children": blocks}
        if after:
            body["after"] = after
        return self._request("PATCH", f"/blocks/{block_id}/children", json=body)

    def delete_block(self, block_id: str) -> dict:
        return self._request("DELETE", f"/blocks/{block_id}")
