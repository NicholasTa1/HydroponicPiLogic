"""Manual smoke test: dummy pH reading -> local SQLite -> Supabase, in one shot.

Run with: python3 test_ph_sync.py
Requires SUPABASE_URL/SUPABASE_KEY set (.env or environment) and supabase_schema.sql applied.
"""

import db
import sync
from sensors.master_basin import PHSensor


def main():
    conn = db.connect()
    ph = PHSensor()

    reading = ph.read()
    print(f"read: {reading}")

    db.insert_reading(conn, reading)
    rows = db.get_all_readings(conn)
    print(f"local rows pending sync: {len(rows)}")

    if sync.send_batch(rows):
        print("sync ok, clearing local buffer")
        db.clear_readings(conn)
    else:
        print("sync failed, leaving local buffer intact")


if __name__ == "__main__":
    main()
