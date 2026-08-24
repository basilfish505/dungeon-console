"""World persistence store factory."""

from __future__ import annotations

import os

from store.base import WorldStore
from store.file_store import FileWorldStore

_store: WorldStore | None = None


def get_world_store() -> WorldStore:
    """Return singleton store: Postgres when DATABASE_URL is set, else JSON files."""
    global _store
    if _store is not None:
        return _store

    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        from store.db import PostgresWorldStore
        _store = PostgresWorldStore(database_url)
    else:
        _store = FileWorldStore()
    _store.ensure_schema()
    return _store


def reset_world_store() -> None:
    """Testing helper: drop cached singleton."""
    global _store
    _store = None
