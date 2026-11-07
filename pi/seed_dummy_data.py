"""Insert 10 cycles of plausible dummy readings (one row each), for testing the BLE transfer without sensors.

    python3 seed_dummy_data.py

Rows are marked synced immediately, so they are visible to BLE (which ignores sync state) but
are never uploaded to Supabase. Dummy values must not pollute the real dataset.

Delete them again with:
    sqlite3 hydro.db "DELETE FROM readings WHERE basin_id = 'dummy';"
"""

import random
import time

import db
from config import SAMPLE_INTERVAL_S

CYCLES = 10
BASIN = "dummy"

# Centre values sit in the lettuce targets from PI_CONTROL_SPEC.md §5, so the app sees
# something realistic rather than obvious filler.
SENSORS = [
    ("ph", 5.8, 0.15),
    ("ec", 1.10, 0.08),
    ("temperature", 22.0, 1.0),
    ("humidity", 60.0, 4.0),
    ("co2", 800.0, 60.0),
    ("water_temp", 19.5, 0.5),
]


def main():
    conn = db.connect()
    now = time.time()

    for cycle in range(CYCLES):
        # Oldest first, ending at now, spaced like the real control loop.
        cycle_ts = now - (CYCLES - 1 - cycle) * SAMPLE_INTERVAL_S
        values = {
            sensor: round(random.gauss(centre, spread / 2), 2)
            for sensor, centre, spread in SENSORS
        }
        db.insert_cycle(conn, BASIN, values, ts=cycle_ts)

    rows = db.get_recent_readings(conn, CYCLES)
    db.mark_synced(conn, [row["id"] for row in rows])

    print(f"inserted {len(rows)} cycles, marked synced (will not upload)")
    print("newest cycle:")
    newest = rows[0]
    for sensor, _, _ in SENSORS:
        print(f"  {sensor:12s} {newest[sensor]:8.2f}")


if __name__ == "__main__":
    main()
