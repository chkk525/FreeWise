"""SQLite snapshot helpers for /admin/backup.

Uses the sqlite3 backup API which is atomic at the page level — readers
and writers can continue against the source DB while the backup runs.
Works for both file-backed and ``:memory:`` engines because we go
through ``engine.raw_connection().driver_connection`` rather than
opening a new sqlite3 handle on the file path.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def make_backup_to_path(engine, out_path: str) -> int:
    """Write an atomic SQLite snapshot of ``engine``'s database to ``out_path``.

    Returns the byte size of the resulting file. Raises ``RuntimeError``
    if the engine is not SQLite.
    """
    if engine.dialect.name != "sqlite":
        raise RuntimeError(
            f"backup only supports sqlite engines, got {engine.dialect.name!r}"
        )
    raw = engine.raw_connection()
    try:
        src = raw.driver_connection
        if not isinstance(src, sqlite3.Connection):
            raise RuntimeError(
                "expected sqlite3.Connection, got "
                f"{type(src).__name__}"
            )
        dst = sqlite3.connect(out_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        raw.close()
    return Path(out_path).stat().st_size
