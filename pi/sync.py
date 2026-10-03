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


# Local sensor name -> column on the remote wide table. Sensors absent here have nowhere to
# land remotely (water_temp has no column, and neither it nor light is implemented yet).
# Readings for those are dropped by send_batch rather than sent.
_REMOTE_COLUMNS = {
    "ph": "ph",
    "ec": "ec",
    "temperature": "temperature_c",
    "humidity": "humidity",
    "light": "light_intensity",
    "co2": "co2",
}


def _row_to_record(row: sqlite3.Row) -> dict | None:
    # The remote table is a wide snapshot row (one column per sensor, no basin_id) rather than
    # our local long format, so each reading lands as its own row with the other columns null.
    column = _REMOTE_COLUMNS.get(row["sensor"])
    if column is None:
        return None

    recorded_at = datetime.datetime.fromtimestamp(row["ts"], tz=datetime.timezone.utc).isoformat()
    return {column: row["value"], "recorded_at": recorded_at}


def send_batch(readings: list[sqlite3.Row]) -> bool:
    """Return True once Supabase has acknowledged the insert.

    Readings with no remote column are skipped rather than raised on: one unmappable sensor
    must not take down the sync loop (and with it every other reading in the batch).
    """
    if not readings:
        return True

    records = []
    skipped = set()
    for row in readings:
        record = _row_to_record(row)
        if record is None:
            skipped.add(row["sensor"])
        else:
            records.append(record)

    if skipped:
        print(f"[sync] no remote column, dropping readings for: {', '.join(sorted(skipped))}")
    if not records:
        return True

    try:
        response = get_client().table(SUPABASE_READINGS_TABLE).insert(records).execute()
    except Exception as exc:
        print(f"[sync] insert failed: {exc}")
        return False

    return len(response.data or []) == len(records)
