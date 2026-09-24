"""Tiny rule-based English lemmatizer for reading analysis (ADR-006 M2).

No ML (Vision no-goal #4): an irregular-forms map plus ordered suffix rules
generate candidate lemmas for a surface token; the reader looks each candidate
up in the words table and the first hit wins. Derived forms therefore match
("forged" → forge, "arose" → arise, "happier" → happy) without external deps.

Precision beats recall here: a missed match renders as "unknown" (tappable,
recoverable); a wrong match would silently lie about what Eddie knows.
"""

from __future__ import annotations

import re

TOKEN_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")

# Common irregular verbs (past/participle → base) and nouns (plural → singular).
IRREGULAR = {
    # verbs
    "was": "be", "were": "be", "been": "be", "is": "be", "are": "be", "am": "be",
    "went": "go", "gone": "go", "did": "do", "done": "do", "had": "have",
    "has": "have", "said": "say", "made": "make", "got": "get", "gotten": "get",
    "took": "take", "taken": "take", "came": "come", "saw": "see", "seen": "see",
    "knew": "know", "known": "know", "gave": "give", "given": "give",
    "found": "find", "thought": "think", "told": "tell", "became": "become",
    "left": "leave", "felt": "feel", "brought": "bring", "began": "begin",
    "begun": "begin", "kept": "keep", "held": "hold", "wrote": "write",
    "written": "write", "stood": "stand", "heard": "hear", "let": "let",
    "meant": "mean", "met": "meet", "ran": "run", "paid": "pay", "sat": "sit",
    "spoke": "speak", "spoken": "speak", "lay": "lie", "led": "lead",
    "read": "read", "grew": "grow", "grown": "grow", "lost": "lose",
    "fell": "fall", "fallen": "fall", "sent": "send", "built": "build",
    "understood": "understand", "drew": "draw", "drawn": "draw",
    "broke": "break", "broken": "break", "spent": "spend", "cut": "cut",
    "rose": "rise", "risen": "rise", "arose": "arise", "arisen": "arise",
    "drove": "drive", "driven": "drive", "bought": "buy", "wore": "wear",
    "worn": "wear", "chose": "choose", "chosen": "choose", "ate": "eat",
    "eaten": "eat", "flew": "fly", "flown": "fly", "forgot": "forget",
    "forgotten": "forget", "slept": "sleep", "threw": "throw", "thrown": "throw",
    "caught": "catch", "taught": "teach", "fought": "fight", "sought": "seek",
    "sold": "sell", "shone": "shine", "shot": "shoot", "sang": "sing",
    "sung": "sing", "sank": "sink", "swam": "swim", "swum": "swim",
    "woke": "wake", "woken": "wake", "won": "win", "wound": "wind",
    "hid": "hide", "hidden": "hide", "hit": "hit", "hurt": "hurt",
    "burst": "burst", "spread": "spread", "struck": "strike", "stuck": "stick",
    "swore": "swear", "sworn": "swear", "tore": "tear", "torn": "tear",
    "froze": "freeze", "frozen": "freeze", "stole": "steal", "stolen": "steal",
    "bore": "bear", "borne": "bear", "beat": "beat", "beaten": "beat",
    "bent": "bend", "bound": "bind", "bled": "bleed", "blew": "blow",
    "blown": "blow", "bred": "breed", "crept": "creep", "dealt": "deal",
    "dug": "dig", "hung": "hang", "knelt": "kneel", "laid": "lay",
    "lent": "lend", "lit": "light", "rode": "ride", "ridden": "ride",
    "rang": "ring", "rung": "ring", "shook": "shake", "shaken": "shake",
    "shut": "shut", "slid": "slide", "spun": "spin", "sprang": "spring",
    "swept": "sweep", "swung": "swing", "wept": "weep",
    # nouns
    "children": "child", "men": "man", "women": "woman", "people": "person",
    "feet": "foot", "teeth": "tooth", "mice": "mouse", "geese": "goose",
    "lives": "life", "wives": "wife", "knives": "knife", "leaves": "leaf",
    "wolves": "wolf", "shelves": "shelf", "halves": "half", "selves": "self",
    "loaves": "loaf", "thieves": "thief",
}

VOWELS = set("aeiou")


def tokens(text: str) -> "list[str]":
    """Surface tokens (words with optional apostrophe part), in order."""
    return TOKEN_RE.findall(text)


def candidates(token: str) -> "list[str]":
    """Candidate lemmas for a surface form, most specific first."""
    t = token.lower().replace("’", "'")
    out = [t]

    if "'" in t:  # don't / it's / worker's → strip the clitic
        out.append(t.split("'")[0])
        t = t.split("'")[0]

    irr = IRREGULAR.get(t)
    if irr:
        out.append(irr)

    def add(c: str) -> None:
        if len(c) >= 2 and c not in out:
            out.append(c)

    n = len(t)
    # plurals / 3rd person
    if t.endswith("ies") and n > 4:
        add(t[:-3] + "y")
    if t.endswith("es") and n > 3:
        add(t[:-2])
        add(t[:-1])
    if t.endswith("s") and not t.endswith("ss") and n > 3:
        add(t[:-1])
    # past
    if t.endswith("ied") and n > 4:
        add(t[:-3] + "y")
    if t.endswith("ed") and n > 3:
        add(t[:-2])          # walked → walk
        add(t[:-1])          # forged → forge
        if n > 4 and t[-3] == t[-4]:
            add(t[:-3])      # stopped → stop
    # gerund
    if t.endswith("ing") and n > 4:
        add(t[:-3])          # walking → walk
        add(t[:-3] + "e")    # forging → forge
        if n > 5 and t[-4] == t[-5]:
            add(t[:-4])      # running → run
    # comparatives
    if t.endswith("ier") and n > 4:
        add(t[:-3] + "y")    # happier → happy
    if t.endswith("iest") and n > 5:
        add(t[:-4] + "y")
    if t.endswith("er") and n > 4:
        add(t[:-2])
        add(t[:-1])
    if t.endswith("est") and n > 5:
        add(t[:-3])
        add(t[:-2])
    # adverbs
    if t.endswith("ly") and n > 4:
        add(t[:-2])          # quickly → quick
        if t.endswith("ily") and n > 5:
            add(t[:-3] + "y")  # happily → happy
    return out


def build_lexicon(body: str, conn) -> "dict[str, dict]":
    """Map each distinct lowercase token of `body` to its matching words row
    (id, status, word, meanings…), resolving derived forms via candidates()."""
    distinct = {t.lower().replace("’", "'") for t in tokens(body)}
    if not distinct:
        return {}

    # One pass over candidate space with a single IN query per chunk.
    cand_map: "dict[str, list[str]]" = {t: candidates(t) for t in distinct}
    all_cands = sorted({c for cs in cand_map.values() for c in cs})
    found: "dict[str, dict]" = {}
    CHUNK = 500
    for i in range(0, len(all_cands), CHUNK):
        chunk = all_cands[i:i + CHUNK]
        q = (f"SELECT id, word, normalized, status, kind, meaning_en, meaning_es, "
             f"pronunciation, example_en, review_count, interval_days, "
             f"audio_word, audio_example "
             f"FROM words WHERE normalized IN ({','.join('?' * len(chunk))})")
        for row in conn.execute(q, chunk):
            found.setdefault(row["normalized"], dict(row))

    lexicon: "dict[str, dict]" = {}
    for tok, cands in cand_map.items():
        for c in cands:
            hit = found.get(c)
            if hit:
                lexicon[tok] = hit
                break
    return lexicon
