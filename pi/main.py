"""Orchestration loop: read every sensor every 30s, buffer in SQLite, sync+clear every 5 min.

Every reading is checked against spec §4 before it is trusted. Failed readings are still
stored, flagged with the reason, but never drive control and never sync. Dosing is still to
come. Outlier/glitch detection over the synced history remains off-Pi.
"""

import time

import db
import sync
from config import BASIN_IDS, SAMPLE_INTERVAL_S, SYNC_BATCH_LIMIT, SYNC_INTERVAL_S
from control import FanController
from validity import ValidityTracker
from sensors.environment import CO2Sensor, HumiditySensor, LightSensor, TemperatureSensor, WaterTempSensor
from sensors.master_basin import ECSensor, PHSensor, WaterLevelSensor


def build_sensors():
    """One list of master-basin sensors, plus one list per basin_id for the per-basin sensors."""
    master = [ECSensor(), PHSensor(), WaterLevelSensor()]

    per_basin = {}
    for basin_id in BASIN_IDS:
        per_basin[basin_id] = [
            TemperatureSensor(basin_id),
            WaterTempSensor(basin_id),
            HumiditySensor(basin_id),
            CO2Sensor(basin_id),
            LightSensor(basin_id),
        ]
    return master, per_basin


def _store(conn, validity, reading) -> bool:
    """Store one reading with its validity verdict. Returns whether it can be trusted.

    Invalid readings are kept, not discarded: they are the record of a fault, and spec §7
    wants the raw data. They simply must not drive anything.
    """
    ts = time.time()
    reason = validity.check(reading.basin_id, reading.sensor, reading.value, ts)
    if reason:
        print(f"[invalid] {reading.sensor} ({reading.basin_id}): {reason}")
    db.insert_reading(conn, reading, ts=ts, invalid_reason=reason)
    return reason is None


def read_all(conn, master_sensors, per_basin_sensors, fan_controllers, validity):
    for sensor in master_sensors:
        try:
            reading = sensor.read()
        except NotImplementedError:
            continue  # hardware not wired up yet
        except Exception as exc:
            print(f"[sensor error] {sensor.name} ({sensor.basin_id}): {exc}")
            continue

        _store(conn, validity, reading)

    for basin_id, sensors in per_basin_sensors.items():
        for sensor in sensors:
            try:
                reading = sensor.read()
            except NotImplementedError:
                continue  # hardware not wired up yet
            except Exception as exc:
                print(f"[sensor error] {sensor.name} ({sensor.basin_id}): {exc}")
                continue

            trusted = _store(conn, validity, reading)
            # Spec §4: never act on a reading that failed its checks. Holding the fan at its
            # current state is safer than driving it from a probe we know is lying.
            if trusted and sensor.name == "temperature":
                fan_controllers[basin_id].update(reading.value)


def sync_pending(conn):
    """Push unsynced readings in batches until the queue drains (spec §8).

    A whole batch is marked synced on success, including readings with no remote column.
    Those have nowhere to go, and leaving them unsynced would park them at the front of the
    oldest-first queue forever, eventually filling every batch and starving real readings.
    """
    while True:
        readings = db.get_unsynced_readings(conn, SYNC_BATCH_LIMIT)
        if not readings:
            return
        if not sync.send_batch(readings):
            print("[sync] batch failed, will retry next cycle")
            return
        db.mark_synced(conn, [row["id"] for row in readings])


def main():
    conn = db.connect()
    master_sensors, per_basin_sensors = build_sensors()
    fan_controllers = {basin_id: FanController(basin_id) for basin_id in BASIN_IDS}
    validity = ValidityTracker()

    last_sync = time.monotonic()

    while True:
        loop_start = time.monotonic()

        read_all(conn, master_sensors, per_basin_sensors, fan_controllers, validity)

        if time.monotonic() - last_sync >= SYNC_INTERVAL_S:
            sync_pending(conn)
            last_sync = time.monotonic()

        elapsed = time.monotonic() - loop_start
        time.sleep(max(0.0, SAMPLE_INTERVAL_S - elapsed))


if __name__ == "__main__":
    main()
