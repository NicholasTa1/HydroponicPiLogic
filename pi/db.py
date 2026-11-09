"""SQLite as the Pi's durable record of every reading, and as the sync queue.

Two tables:

- `readings`: one wide row per sampling cycle per grow basin, one column per sensor. A column
  is NULL when that sensor gave no trusted value this cycle (failed validity, raised an error,
  or is not wired up yet). Master-basin values (pH, EC, water level) are shared by every grow
  basin, so they are written into each basin's row.
- `faults`: one row per reading that failed a validity check or raised an error, with the raw
  value and the reason. This is the record of what went wrong behind each NULL, which spec §7
  wants kept. Faults never sync.

Readings are kept, not deleted: spec §7 wants full 30s resolution for the whole crop cycle
because the capstone analysis needs raw data, and spec §8 wants local retention and sync status
treated as separate concerns. Synced rows are therefore marked rather than removed, which also
lets a second process (BLE) serve history without racing the sync cycle.
"""

from __future__ import annotations

import sqlite3
import time

from config import DB_PATH, SQLITE_BUSY_TIMEOUT_S

# One column per sensor, named after Sensor.name. Fixed here rather than built from input, so
# column names can be put into SQL safely. Units are implied by the sensor:
# pH, mS/cm, 0/1, C, C, %, ppm, lux.
SENSOR_COLUMNS = (
    "ph",
    "ec",
    "water_level",
    "temperature",
    "water_temp",
    "humidity",
    "co2",
    "light",
)

_SCHEMA = (
    f"""
    CREATE TABLE IF NOT EXISTS readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        basin_id TEXT NOT NULL,
        {", ".join(f"{column} REAL" for column in SENSOR_COLUMNS)},
        synced INTEGER NOT NULL DEFAULT 0
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS faults (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        basin_id TEXT NOT NULL,
        sensor TEXT NOT NULL,
        value REAL,
        reason TEXT NOT NULL
    );
    """,
)

_INDEXES = (
    # Partial index: holds only unsynced rows, so it stays small no matter how large the table
    # grows. Without it, finding the sync queue degrades into a full scan.
    "CREATE INDEX IF NOT EXISTS readings_unsynced_idx ON readings (ts) WHERE synced = 0;",
    # Full index on ts, for the BLE "newest N cycles" query, which the partial index cannot
    # serve because it excludes synced rows.
    "CREATE INDEX IF NOT EXISTS readings_ts_idx ON readings (ts);",
    "CREATE INDEX IF NOT EXISTS faults_ts_idx ON faults (ts);",
)


def connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=SQLITE_BUSY_TIMEOUT_S)
    # WAL lets other processes (BLE, CV) read while the control loop writes, instead of
    # intermittent "database is locked". It is a persistent property of the file, set once.
    conn.execute("PRAGMA journal_mode=WAL")
    _retire_long_table(conn)
    for statement in _SCHEMA:
        conn.execute(statement)
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


def _retire_long_table(conn: sqlite3.Connection) -> None:
    """Databases from before 2026-11-03 stored one row per reading. Keep that data, renamed to
    readings_long, rather than deleting it; it is not read or synced by anything any more.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(readings)")}
    if "sensor" not in columns:
        return
    conn.execute("ALTER TABLE readings RENAME TO readings_long")
    # Renaming a table keeps its indexes under their old names, which would stop the new
    # table's indexes from being created.
    conn.execute("DROP INDEX IF EXISTS readings_unsynced_idx")
    conn.execute("DROP INDEX IF EXISTS readings_ts_idx")
    conn.commit()


def insert_cycle(
    conn: sqlite3.Connection,
    basin_id: str,
    values: dict[str, float | None],
    ts: float | None = None,
) -> None:
    """Store one cycle for one basin. Sensors missing from `values` are stored as NULL."""
    unknown = set(values) - set(SENSOR_COLUMNS)
    if unknown:
        raise ValueError(f"no column for sensor(s): {', '.join(sorted(unknown))}")

    columns = ", ".join(SENSOR_COLUMNS)
    placeholders = ", ".join("?" for _ in SENSOR_COLUMNS)
    conn.execute(
        f"INSERT INTO readings (ts, basin_id, {columns}) VALUES (?, ?, {placeholders})",
        (
            ts if ts is not None else time.time(),
            basin_id,
            *(values.get(column) for column in SENSOR_COLUMNS),
        ),
    )
    conn.commit()


def insert_fault(
    conn: sqlite3.Connection,
    basin_id: str,
    sensor: str,
    value: float | None,
    reason: str,
    ts: float | None = None,
) -> None:
    """Record a reading that cannot be trusted. Committed immediately, so a crash later in the
    cycle does not lose the evidence. `value` is None when the sensor raised instead of reading.
    """
    conn.execute(
        "INSERT INTO faults (ts, basin_id, sensor, value, reason) VALUES (?, ?, ?, ?, ?)",
        (ts if ts is not None else time.time(), basin_id, sensor, value, reason),
    )
    conn.commit()


def get_unsynced_readings(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Oldest-first so a backlog drains in order. One row is one cycle for one basin."""
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
    """Newest-first cycles, independent of sync state. For the BLE read path."""
    return conn.execute(
        "SELECT * FROM readings ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()


def get_recent_faults(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Newest-first faults, for diagnosing a probe."""
    return conn.execute(
        "SELECT * FROM faults ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()
