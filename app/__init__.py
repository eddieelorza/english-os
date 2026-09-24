"""English Learning OS — local core (ADR-006).

`app/` is the local-first layer: SQLite as system of record, importers from
the legacy stores (Anki, Notion, learner_profile.json), and — in later
milestones — the FastAPI app, FSRS scheduler, AIProvider and Obsidian export.
"""
