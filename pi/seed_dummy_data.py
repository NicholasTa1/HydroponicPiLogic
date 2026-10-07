"""Insert 10 cycles of plausible dummy readings, for testing the BLE transfer without sensors.

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
from sensors.base import Reading

CYCLES = 10
BASIN = "dummy"

# Centre values sit in the lettuce targets from PI_CONTROL_SPEC.md §5, so the app sees
# something realistic rather than obvious filler.
SENSORS = [
    ("ph", 5.8, 0.15, "pH"),
    ("ec", 1.10, 0.08, "mS/cm"),
    ("temperature", 22.0, 1.0, "C"),
    ("humidity", 60.0, 4.0, "pct"),
    ("co2", 800.0, 60.0, "ppm"),
    ("water_temp", 19.5, 0.5, "C"),   # no app column: exercises the drop path
]


def main():
    conn = db.connect()
    now = time.time()
    ids = []

    for cycle in range(CYCLES):
        # Oldest first, ending at now, spaced like the real control loop.
        cycle_ts = now - (CYCLES - 1 - cycle) * SAMPLE_INTERVAL_S
        for offset, (sensor, centre, spread, unit) in enumerate(SENSORS):
            value = round(random.gauss(centre, spread / 2), 2)
            db.insert_reading(
                conn,
                Reading(BASIN, sensor, value, unit),
                ts=cycle_ts + offset * 0.05,
            )

    ids = [row["id"] for row in db.get_recent_readings(conn, CYCLES * len(SENSORS))]
    db.mark_synced(conn, ids)

    print(f"inserted {len(ids)} readings across {CYCLES} cycles, marked synced (will not upload)")
    print("newest cycle:")
    for row in db.get_recent_readings(conn, len(SENSORS)):
        print(f"  {row['sensor']:12s} {row['value']:8.2f} {row['unit']}")


if __name__ == "__main__":
    main()
