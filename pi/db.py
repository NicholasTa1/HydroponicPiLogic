"""SQLite as the Pi's durable record of every reading, and as the sync queue.

Readings are kept, not deleted: spec §7 wants full 30s resolution for the whole crop cycle
because the capstone analysis needs raw data, and spec §8 wants local retention and sync status
treated as separate concerns. Synced rows are therefore marked rather than removed, which also
lets a second process (BLE) serve history without racing the sync cycle.

A full crop cycle is roughly 800k rows / under 100MB, which is nothing on an SD card.
"""

from __future__ import annotations

import sqlite3
import time

from config import DB_PATH, SQLITE_BUSY_TIMEOUT_S
from sensors.base import Reading

_SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    basin_id TEXT NOT NULL,
    sensor TEXT NOT NULL,
    value REAL,
    unit TEXT NOT NULL,
    synced INTEGER NOT NULL DEFAULT 0
);
"""

_INDEXES = (
    # Partial index: holds only unsynced rows, so it stays small (a few hundred entries) no
    # matter how large the table grows. Without it, finding the sync queue degrades into a
    # full scan — which stays fast for the first week and then quietly does not.
    "CREATE INDEX IF NOT EXISTS readings_unsynced_idx ON readings (ts) WHERE synced = 0;",
    # Full index on ts. The partial index above cannot serve "newest N readings" because it
    # excludes synced rows, which is nearly the whole table. This is what keeps the BLE
    # history query from scanning and sorting every row.
    "CREATE INDEX IF NOT EXISTS readings_ts_idx ON readings (ts);",
)


def connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=SQLITE_BUSY_TIMEOUT_S)
    # WAL lets other processes (BLE, CV) read while the control loop writes, instead of
    # intermittent "database is locked". It is a persistent property of the file, set once.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_SCHEMA)
    _add_synced_column_if_missing(conn)
    for index in _INDEXES:
        conn.execute(index)
    conn.commit()
    conn.row_factory = sqlite3.Row
    return conn


def connect_readonly(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Read-only handle for other processes. Cannot create or migrate anything, by design."""
    conn = sqlite3.connect(
        f"file:{db_path}?mode=ro", uri=True, timeout=SQLITE_BUSY_TIMEOUT_S
    )
    conn.row_factory = sqlite3.Row
    return conn


def _add_synced_column_if_missing(conn: sqlite3.Connection) -> None:
    """Migrate databases created before readings carried sync state."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(readings)")}
    if "synced" not in columns:
        conn.execute("ALTER TABLE readings ADD COLUMN synced INTEGER NOT NULL DEFAULT 0")


def insert_reading(conn: sqlite3.Connection, reading: Reading, ts: float | None = None) -> None:
    conn.execute(
        "INSERT INTO readings (ts, basin_id, sensor, value, unit) VALUES (?, ?, ?, ?, ?)",
        (ts if ts is not None else time.time(), reading.basin_id, reading.sensor, reading.value, reading.unit),
    )
    conn.commit()


def get_unsynced_readings(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Oldest-first so a backlog drains in order."""
    return conn.execute(
        "SELECT * FROM readings WHERE synced = 0 ORDER BY ts LIMIT ?", (limit,)
    ).fetchall()


def mark_synced(conn: sqlite3.Connection, ids: list[int]) -> None:
    """Call only once the server has acknowledged the batch."""
    if not ids:
        return
    conn.executemany("UPDATE readings SET synced = 1 WHERE id = ?", [(i,) for i in ids])
    conn.commit()


def get_recent_readings(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Newest-first history, independent of sync state. For the BLE read path."""
    return conn.execute(
        "SELECT * FROM readings ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()
