import os
import requests

NOTION_TOKEN = (os.environ.get("NOTION_TOKEN") or "").strip()
VOCAB_DB_ID = (os.environ.get("VOCAB_DB_ID") or "").strip()

if not NOTION_TOKEN or not VOCAB_DB_ID:
    raise SystemExit("Faltan variables: NOTION_TOKEN y/o VOCAB_DB_ID")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

session = requests.Session()

# ===== Ajusta si tus propiedades se llaman diferente =====
PROP_USED = "Used Today"  # Checkbox en Vocabulary Master
# ========================================================

def notion_query(db_id: str, body: dict):
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    r = session.post(url, headers=HEADERS, json=body, timeout=30)
    if not r.ok:
        print("NOTION ERROR:", r.status_code, r.text)
        r.raise_for_status()
    return r.json()

def notion_update_page(page_id: str, props: dict):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    r = session.patch(url, headers=HEADERS, json={"properties": props}, timeout=30)
    if not r.ok:
        print("NOTION ERROR:", r.status_code, r.text)
        r.raise_for_status()

def reset_used_today():
    body = {
        "filter": {
            "property": PROP_USED,
            "checkbox": {"equals": True}
        }
    }

    reset_count = 0
    next_cursor = None

    while True:
        if next_cursor:
            body["start_cursor"] = next_cursor

        data = notion_query(VOCAB_DB_ID, body)
        results = data.get("results", [])

        for page in results:
            notion_update_page(page["id"], {PROP_USED: {"checkbox": False}})
            reset_count += 1

        if data.get("has_more"):
            next_cursor = data.get("next_cursor")
        else:
            break

    print(f"🧹 Reset completo. Used Today limpiadas: {reset_count}")

if __name__ == "__main__":
    reset_used_today()
