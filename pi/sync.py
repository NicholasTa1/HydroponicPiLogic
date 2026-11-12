"""Push a batch of readings to the remote Supabase Postgres table. Rows are only marked
synced locally (db.mark_synced) after this confirms the batch landed.
"""

from __future__ import annotations

import sqlite3

from supabase import Client, create_client

from config import (
    REMOTE_COLUMNS,
    SUPABASE_KEY,
    SUPABASE_READINGS_TABLE,
    SUPABASE_URL,
    remote_record,
)

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError(
                "SUPABASE_URL/SUPABASE_KEY not set — copy .env.example to .env and fill them in"
            )
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def _row_to_record(row: sqlite3.Row) -> dict | None:
    """One local cycle row becomes one remote row, keyed by the remote column names.

    Values that failed their validity checks are already NULL locally, so known-bad numbers
    never reach the dashboard. Returns None when the row has nothing to send.
    """
    record = remote_record(row)  # the same record BLE sends (see config.remote_record)
    if all(record[remote] is None for remote in REMOTE_COLUMNS.values()):
        return None
    return record


def send_batch(readings: list[sqlite3.Row]) -> bool:
    """Return True once Supabase has acknowledged the insert.

    Every record carries every mapped column (NULL where there was no trusted value), so all
    records in one insert share the same shape.
    """
    records = [record for record in map(_row_to_record, readings) if record is not None]
    if not records:
        return True

    try:
        response = get_client().table(SUPABASE_READINGS_TABLE).insert(records).execute()
    except Exception as exc:
        print(f"[sync] insert failed: {exc}")
        return False

    return len(response.data or []) == len(records)
