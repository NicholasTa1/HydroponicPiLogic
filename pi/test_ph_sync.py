"""Manual smoke test: dummy pH reading -> local SQLite -> Supabase, in one shot.

Run with: python3 test_ph_sync.py
Requires SUPABASE_URL/SUPABASE_KEY set (.env or environment) and supabase_schema.sql applied.
"""

import db
import sync
from config import SYNC_BATCH_LIMIT
from sensors.master_basin import PHSensor


def main():
    conn = db.connect()
    ph = PHSensor()

    reading = ph.read()
    print(f"read: {reading}")

    db.insert_reading(conn, reading)
    rows = db.get_unsynced_readings(conn, SYNC_BATCH_LIMIT)
    print(f"local rows pending sync: {len(rows)}")

    if sync.send_batch(rows):
        db.mark_synced(conn, [row["id"] for row in rows])
        print("sync ok, rows marked synced (kept locally)")
    else:
        print("sync failed, rows left unsynced for retry")


if __name__ == "__main__":
    main()
