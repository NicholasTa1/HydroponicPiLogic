"""SQLite as a short-lived buffer: hold ~5 minutes of readings, hand them to sync, clear on ack.

This intentionally does NOT keep long-term history on the Pi (that lives in Supabase/the app) —
see PI_CONTROL_SPEC.md for the earlier full-retention design if that tradeoff gets revisited.
"""

from __future__ import annotations

import sqlite3
import time

from config import DB_PATH
from sensors.base import Reading

_SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    basin_id TEXT NOT NULL,
    sensor TEXT NOT NULL,
    value REAL,
    unit TEXT NOT NULL
);
"""


def connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def insert_reading(conn: sqlite3.Connection, reading: Reading, ts: float | None = None) -> None:
    conn.execute(
        "INSERT INTO readings (ts, basin_id, sensor, value, unit) VALUES (?, ?, ?, ?, ?)",
        (ts if ts is not None else time.time(), reading.basin_id, reading.sensor, reading.value, reading.unit),
    )
    conn.commit()


def get_all_readings(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute("SELECT * FROM readings ORDER BY ts").fetchall()


def clear_readings(conn: sqlite3.Connection) -> None:
    """Only call this after the batch has been acknowledged by sync — see main.py."""
    conn.execute("DELETE FROM readings")
    conn.commit()
