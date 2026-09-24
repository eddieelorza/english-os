import os
import datetime as dt
import requests

# ==============================
# ENV VARIABLES
# ==============================

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
VOCAB_DB_ID = os.environ.get("VOCAB_DB_ID")
READING_DB_ID = os.environ.get("READING_DB_ID")

if not NOTION_TOKEN or not VOCAB_DB_ID or not READING_DB_ID:
    raise SystemExit("❌ Missing environment variables: NOTION_TOKEN, VOCAB_DB_ID, READING_DB_ID")

# ✅ CAMBIA ESTO si tu title property se llama diferente (por ejemplo "Name")
READING_TITLE_PROP = "Title"

# ✅ Cambia si tu vocab title property no se llama "Word"
VOCAB_WORD_PROP = "Word"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

session = requests.Session()
def notion_query(db_id, body):
    r = session.post(
        f"https://api.notion.com/v1/databases/{db_id}/query",
        headers=HEADERS,
        json=body,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()

def notion_get_children(block_id):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    all_results = []
    cursor = None

    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor

        r = session.get(url, headers=HEADERS, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        all_results.extend(data.get("results", []))

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return all_results

def append_children(page_id, blocks):
    session.patch(
        f"https://api.notion.com/v1/blocks/{page_id}/children",
        headers=HEADERS,
        json={"children": blocks},
        timeout=30,
    ).raise_for_status()

def find_reading_page_for_today():
    today = dt.date.today().isoformat()
    page_title = f"Reading – {today}"

    body = {
        "filter": {
            "property": READING_TITLE_PROP,
            "title": {"equals": page_title}
        }
    }
    res = notion_query(READING_DB_ID, body).get("results", [])
    return res[0] if res else None

def extract_words_bullets_from_blocks(blocks):
    """
    Saca bullets tipo '• word' de paragraphs (como tu sección 'Words Today').
    Devuelve set en lowercase.
    """
    words = set()

    for b in blocks:
        btype = b.get("type")
        if btype != "paragraph":
            continue

        rt_list = b.get("paragraph", {}).get("rich_text", [])
        text = "".join(x.get("plain_text", "") for x in rt_list).strip()
        if not text:
            continue

        for line in text.splitlines():
            line = line.strip()
            if line.startswith("•"):
                w = line.lstrip("•").strip()
                if w:
                    words.add(w.lower())

    return words

# ==============================
# GET WORDS REVIEWED TODAY
# ==============================

def get_words_reviewed_today(limit=None):
    now = dt.datetime.now().astimezone()
    start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = start_dt + dt.timedelta(days=1)

    body = {
        "page_size": 100,
        "filter": {
            "and": [
                # "Synced On" (date real del pipeline) en vez de "Last Reviewed",
                # que es last_edited_time y se mueve con cualquier edición.
                {"property": "Synced On", "date": {"equals": dt.date.today().isoformat()}},
            ]
        },
        "sorts": [{"property": "Word", "direction": "ascending"}],
    }

    all_results = []
    start_cursor = None

    while True:
        if start_cursor:
            body["start_cursor"] = start_cursor
        elif "start_cursor" in body:
            body.pop("start_cursor")

        r = session.post(
            f"https://api.notion.com/v1/databases/{VOCAB_DB_ID}/query",
            headers=HEADERS,
            json=body,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()

        all_results.extend(data.get("results", []))

        if limit and len(all_results) >= limit:
            return all_results[:limit]

        if not data.get("has_more"):
            break
        start_cursor = data.get("next_cursor")

    return all_results


def get_word(page):
    prop = page["properties"].get(VOCAB_WORD_PROP, {})
    title = prop.get("title", [])
    if not title:
        return ""
    return title[0]["text"]["content"]


def rt(text: str):
    text = (text or "").strip()
    if not text:
        return []
    if len(text) > 1900:
        text = text[:1900] + "…"
    return [{"type": "text", "text": {"content": text}}]


# ==============================
# CREATE READING PAGE
# ==============================

def create_or_update_reading_page(words):
    today = dt.date.today().isoformat()
    page_title = f"Reading – {today}"

    # palabras del día desde vocab
    words_list = []
    for w in words:
        ww = get_word(w)
        if ww:
            words_list.append(ww)

    if not words_list:
        words_list = ["(no words reviewed today)"]

    existing = find_reading_page_for_today()

    # -----------------------------
    # SI NO EXISTE: CREAR NORMAL
    # -----------------------------
    if not existing:
        word_list_text = "\n".join([f"• {w}" for w in words_list])

        # Python solo pone los DATOS del día. La historia y las preguntas las
        # escribe la routine de Claude (ADR-003): generar aquí un prompt y unas
        # preguntas genéricas solo duplicaba y ensuciaba la página.
        content_blocks = [
            {"object": "block", "type": "heading_2", "heading_2": {"rich_text": rt("📌 Words Today")}},
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt(word_list_text)}},

            {"object": "block", "type": "heading_2", "heading_2": {"rich_text": rt("📖 Story")}},
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt("⏳ Generando tu historia…")}},
        ]

        body = {
            "parent": {"database_id": READING_DB_ID},
            "properties": {
                READING_TITLE_PROP: {"title": [{"text": {"content": page_title}}]},
                "Date": {"date": {"start": today}},
            },
            "children": content_blocks,
        }

        r = session.post("https://api.notion.com/v1/pages", headers=HEADERS, json=body, timeout=30)
        if not r.ok:
            print("❌ NOTION ERROR:", r.status_code)
            print(r.text)
            r.raise_for_status()

        print(f"🆕 Created: {page_title}")
        return

    # -----------------------------
    # SI YA EXISTE: SOLO ANEXAR NUEVAS
    # -----------------------------
    page_id = existing["id"]
    current_blocks = notion_get_children(page_id)
    already = extract_words_bullets_from_blocks(current_blocks)

    new_words = [w for w in words_list if w.lower() not in already]

    if not new_words:
        print(f"✅ Reading ya existe y no hay nuevas palabras para anexar: {page_title}")
        return

    word_list_text = "\n".join([f"• {w}" for w in new_words])

    inc_blocks = [
        {"object": "block", "type": "divider", "divider": {}},
        {"object": "block", "type": "heading_2", "heading_2": {"rich_text": rt("➕ New words added later")}},
        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt(word_list_text)}},
    ]

    append_children(page_id, inc_blocks)
    print(f"✅ Appended {len(new_words)} new words to: {page_title}")


# ==============================
# MAIN
# ==============================

if __name__ == "__main__":
    words_today = get_words_reviewed_today(limit=None)

    print(f"📌 Words today: {len(words_today)}")
    for w in words_today:
        print("   -", get_word(w))

    create_or_update_reading_page(words_today)
