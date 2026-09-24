"""Importers: legacy stores → SQLite (ADR-006 M0).

Each module exposes `run(conn) -> dict` returning counter stats. All are
idempotent — safe to re-run daily as the dual-write step of the pipeline.
"""
