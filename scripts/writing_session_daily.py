"""
writing_session_daily.py  – versión mejorada
Cambios: ejercicios estructurados, rotación de tense por día de semana,
         guarda Tense Focus en propiedad de Notion.
"""

import os
import datetime as dt
import random
import requests

NOTION_TOKEN = (os.environ.get("NOTION_TOKEN") or "").strip()
VOCAB_DB_ID  = (os.environ.get("VOCAB_DB_ID")  or "").strip()
WRITING_DB_ID= (os.environ.get("WRITING_DB_ID")or "").strip()

if not NOTION_TOKEN or not VOCAB_DB_ID or not WRITING_DB_ID:
    raise SystemExit("Faltan variables de entorno.")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}
session = requests.Session()

# "Last Reviewed" en Notion es de tipo last_edited_time: cualquier edición de
# la fila (incluso limpiar un campo) la marcaría como "de hoy". "Synced On" es
# una date real que solo escribe el pipeline → es la fuente correcta.
VOCAB_SYNCED_ON_PROP = "Synced On"
VOCAB_WORD_PROP          = "Word"
VOCAB_MEANING_EN_PROP    = "Meaning (EN)"
VOCAB_MEANING_ES_PROP    = "Meaning (ES)"
WRITING_TITLE_PROP       = "Task"
WRITING_DATE_PROP        = "Date"
WRITING_CORRECTED_PROP   = "Corrected"
WRITING_TENSE_PROP       = "Tense Focus"
TZ_OFFSET                = "-06:00"

TENSE_BY_WEEKDAY = {
    0: "Present Simple",
    1: "Past Simple",
    2: "Present Continuous",
    3: "Present Perfect",
    4: "Future (will / going to)",
    5: "Past Simple",
    6: "Present Perfect",
}

# ── helpers ──────────────────────────────────────────────────────────────

def rt(text, limit=2000):
    text = text or ""
    parts = [text[i:i+limit] for i in range(0, len(text), limit)] or [""]
    return [{"type": "text", "text": {"content": p}} for p in parts]

def heading(text, level=2):
    k = f"heading_{level}"
    return {"object":"block","type":k, k:{"rich_text":rt(text)}}

def paragraph(text):
    return {"object":"block","type":"paragraph","paragraph":{"rich_text":rt(text)}}

def paragraph_blocks(text, limit=1800):
    text = text or ""
    parts = [text[i:i+limit] for i in range(0, len(text), limit)] or [""]
    return [{"object":"block","type":"paragraph",
             "paragraph":{"rich_text":[{"type":"text","text":{"content":p}}]}}
            for p in parts]

def divider():
    return {"object":"block","type":"divider","divider":{}}

def callout(text, emoji="✍️"):
    return {"object":"block","type":"callout",
            "callout":{"rich_text":rt(text),"icon":{"type":"emoji","emoji":emoji}}}

def table_block(rows):
    table_rows = [{"object":"block","type":"table_row",
                   "table_row":{"cells":[rt("Word"),rt("ES")]}}]
    for word, es in rows:
        table_rows.append({"object":"block","type":"table_row",
                            "table_row":{"cells":[rt(word),rt(es)]}})
    return {"object":"block","type":"table",
            "table":{"table_width":2,"has_column_header":True,
                     "has_row_header":False,"children":table_rows}}

def todo_list(words):
    return [{"object":"block","type":"to_do",
             "to_do":{"rich_text":rt(w),"checked":False}} for w in words]

def notion_query(db_id, body):
    r = session.post(f"https://api.notion.com/v1/databases/{db_id}/query",
                     headers=HEADERS, json=body)
    r.raise_for_status(); return r.json()

def notion_create(body):
    r = session.post("https://api.notion.com/v1/pages",
                     headers=HEADERS, json=body, timeout=30)
    if not r.ok:
        print("NOTION CREATE ERROR", r.status_code, r.text); raise SystemExit(1)
    return r.json()

def notion_update(page_id, props):
    r = session.patch(f"https://api.notion.com/v1/pages/{page_id}",
                      headers=HEADERS, json={"properties": props})
    r.raise_for_status()

def notion_get_children(block_id):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    all_results, cursor = [], None
    while True:
        params = {"page_size": 100}
        if cursor: params["start_cursor"] = cursor
        r = session.get(url, headers=HEADERS, params=params, timeout=30)
        r.raise_for_status(); data = r.json()
        all_results.extend(data.get("results", []))
        if not data.get("has_more"): break
        cursor = data.get("next_cursor")
    return all_results

def append_children(page_id, blocks):
    session.patch(f"https://api.notion.com/v1/blocks/{page_id}/children",
                  headers=HEADERS, json={"children": blocks}).raise_for_status()

def extract_words_from_todos(blocks):
    words = set()
    for b in blocks:
        if b.get("type") != "to_do": continue
        text = "".join(x.get("plain_text","") for x in b.get("to_do",{}).get("rich_text",[])).strip()
        if text: words.add(text.lower())
    return words

def get_rich_text_prop(props, name):
    p = props.get(name, {})
    if p.get("type") != "rich_text": return ""
    return "".join(x.get("plain_text","") for x in p.get("rich_text",[]))

def get_title_prop(props, name):
    p = props.get(name, {})
    if p.get("type") != "title": return ""
    return "".join(x.get("plain_text","") for x in p.get("title",[]))

def today_range():
    d0 = dt.date.today(); d1 = d0 + dt.timedelta(days=1)
    return f"{d0.isoformat()}T00:00:00{TZ_OFFSET}", f"{d1.isoformat()}T00:00:00{TZ_OFFSET}"

# ── words ─────────────────────────────────────────────────────────────────

def get_today_words():
    start, end = today_range()
    body = {"filter":{"and":[
        {"property":VOCAB_SYNCED_ON_PROP,"date":{"equals":dt.date.today().isoformat()}},
    ]}}
    results = notion_query(VOCAB_DB_ID, body)["results"]
    print(f"📚 Palabras hoy: {len(results)}")
    return results

# ── exercises ─────────────────────────────────────────────────────────────

def build_exercises(words_list, tense):
    sample = list(words_list[:12])
    random.shuffle(sample)

    def g(i, size=3):
        start = i * size
        chunk = sample[start:start+size]
        return chunk if chunk else sample[:size]

    tense_tip = {
        "Present Simple":            "Use: do/does + base verb. E.g. 'She works every day.'",
        "Past Simple":               "Use: did + base / verb-ed. E.g. 'He ran yesterday.'",
        "Present Continuous":        "Use: am/is/are + verb-ing. E.g. 'She is reading now.'",
        "Present Perfect":           "Use: have/has + past participle. E.g. 'I have studied today.'",
        "Future (will / going to)":  "will = spontaneous. going to = planned. E.g. 'I'm going to study.'",
    }
    tip = tense_tip.get(tense, "")

    w_a = ", ".join(f"**{w}**" for w in g(0))
    w_b = ", ".join(f"**{w}**" for w in g(1))
    w_c = g(2)
    w1  = w_c[0] if w_c else "happy"
    w2  = w_c[1] if len(w_c) > 1 else "continue"

    return f"""📌 Instructions: Write your answers below each exercise. Use the word(s) in **bold**. When done → tell Claude: "ya terminé, revísame"

---

### 1️⃣ {tense} — *{tip}*

**Exercise A — Write 2 sentences using:**
{w_a}
→ Sentence 1:
→ Sentence 2:

**Exercise B — Correct this sentence (wrong tense/form):**
*"She go to work and help a lot of people every day."*
→ Your correction:

---

### ✍️ Free Writing — Write a short paragraph (4–6 sentences):
Use ALL of these: {w_b}
→ Your paragraph:

---

### 🔄 Transform to {tense}:
*"The team work hard and achieve their goal."*
→ Your sentence:

---

### 🔗 Connector Challenge:
Join these two ideas (use: however / although / because / therefore / even though):
- "She felt **{w1}**."
- "She decided to **{w2}**."
→ Your sentence:

---

### 🌟 Bonus — Creative sentence:
Use at least 3 of today's words in ONE sentence (any tense):
→ Your sentence:

---

🧠 Notes / doubts:"""

# ── blocks ────────────────────────────────────────────────────────────────

def build_blocks(pages):
    rows, words_only, meanings_en = [], [], []
    for p in pages:
        props = p["properties"]
        word = get_title_prop(props, VOCAB_WORD_PROP)
        if not word: continue
        es = get_rich_text_prop(props, VOCAB_MEANING_ES_PROP)
        en = get_rich_text_prop(props, VOCAB_MEANING_EN_PROP)
        rows.append((word, es)); words_only.append(word)
        if en: meanings_en.append(f"• {word}: {en[:160]}")

    tense = TENSE_BY_WEEKDAY[dt.date.today().weekday()]

    # Python solo pone los DATOS (las palabras del día y su checklist, que es
    # lo que lee sync_used_words). Las actividades las escribe la routine de
    # Claude (ADR-003) apuntando a los errores reales de Eddie: los ejercicios
    # fijos que había aquí eran genéricos y la routine los reemplazaba igual.
    blocks = [
        heading("🧠 Vocabulary Today"),
        *todo_list(words_only),
        divider(),
        heading("✍️ Writing Practice"),
        callout(f"Focus: {tense} · Tus actividades aparecen aquí en unos minutos.\n"
                f"Cuando termines de escribir, marca ☑ Ready for Review en las "
                f"propiedades de esta página y te llega la corrección.", "✍️"),
    ]
    return blocks, tense


def build_increment_blocks(new_pages):
    rows, words_only, meanings_en = [], [], []
    for p in new_pages:
        props = p["properties"]
        word = get_title_prop(props, VOCAB_WORD_PROP).strip()
        if not word: continue
        es = get_rich_text_prop(props, VOCAB_MEANING_ES_PROP).strip()
        en = get_rich_text_prop(props, VOCAB_MEANING_EN_PROP).strip()
        rows.append((word, es)); words_only.append(word)
        if en: meanings_en.append(f"• {word}: {en[:160]}")
    if not words_only: return []
    return [
        divider(),
        heading("➕ Palabras añadidas después"),
        *todo_list(words_only),
    ]

# ── main ──────────────────────────────────────────────────────────────────

def run():
    today = dt.date.today().isoformat()
    title = f"Writing Session – {today}"
    words = get_today_words()

    existing = notion_query(WRITING_DB_ID, {
        "filter": {"property": WRITING_TITLE_PROP, "title": {"equals": title}}
    })["results"]

    blocks, tense = build_blocks(words)
    props = {
        WRITING_TITLE_PROP:    {"title": [{"text": {"content": title}}]},
        WRITING_DATE_PROP:     {"date": {"start": today}},
        WRITING_CORRECTED_PROP:{"checkbox": False},
        WRITING_TENSE_PROP:    {"select": {"name": tense}},
    }

    if existing:
        page_id = existing[0]["id"]
        notion_update(page_id, props)
        already = extract_words_from_todos(notion_get_children(page_id))
        new_pages = [p for p in words
                     if get_title_prop(p["properties"], VOCAB_WORD_PROP).strip().lower()
                     not in already]
        print(f"➕ Nuevas para anexar: {len(new_pages)}")
        if new_pages:
            append_children(page_id, build_increment_blocks(new_pages))
            print("✅ Appended")
        else:
            print("✅ Ya estaba al día")
    else:
        notion_create({"parent": {"database_id": WRITING_DB_ID},
                       "properties": props, "children": blocks})
        print(f"🆕 Created — tense: {tense}")

if __name__ == "__main__":
    run()
