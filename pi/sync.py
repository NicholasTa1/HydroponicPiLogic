"""Push a batch of readings to the remote Supabase Postgres table. Table is only cleared
locally (see db.clear_readings) after this confirms the batch landed.
"""

from __future__ import annotations

import datetime
import sqlite3

from supabase import Client, create_client

from config import SUPABASE_KEY, SUPABASE_READINGS_TABLE, SUPABASE_URL

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


def _row_to_record(row: sqlite3.Row) -> dict:
    # The remote table is a wide snapshot row (one column per sensor, no basin_id) rather than
    # our local long format. Only pH is mapped for now — extend this once other sensors/basins
    # need to land remotely too.
    if row["sensor"] != "ph":
        raise NotImplementedError(f"no remote column mapping yet for sensor={row['sensor']!r}")

    recorded_at = datetime.datetime.fromtimestamp(row["ts"], tz=datetime.timezone.utc).isoformat()
    return {"ph": row["value"], "recorded_at": recorded_at}


def send_batch(readings: list[sqlite3.Row]) -> bool:
    """Return True once Supabase has acknowledged the insert."""
    if not readings:
        return True

    records = [_row_to_record(row) for row in readings]

    try:
        response = get_client().table(SUPABASE_READINGS_TABLE).insert(records).execute()
    except Exception as exc:
        print(f"[sync] insert failed: {exc}")
        return False

    return len(response.data or []) == len(records)
