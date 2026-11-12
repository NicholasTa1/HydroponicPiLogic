"""Orchestration loop: read every sensor every 30s, store one row per cycle, sync every 5 min.

Every reading is checked against spec §4 before it is trusted. A failed reading is stored as
NULL in that cycle's row, with its raw value and reason recorded in the faults table, and never
drives control or syncs. Dosing is still to come. Outlier/glitch detection over the synced
history remains off-Pi.
"""

from __future__ import annotations

import time

import db
import sync
from config import (
    BASIN_IDS,
    DEVICE_ID_SOURCE,
    DEVICE_NAME,
    SAMPLE_INTERVAL_S,
    SYNC_BATCH_LIMIT,
    SYNC_INTERVAL_S,
    SYSTEM_NAME,
)
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


def _read_trusted(conn, validity, sensor) -> float | None:
    """Read one sensor and return its value only if it can be trusted, else None.

    Untrusted readings are not discarded: the raw value and the reason go into the faults
    table, because they are the record of a fault (spec §7). They simply must not drive
    anything or reach the synced dataset.
    """
    ts = time.time()
    try:
        reading = sensor.read()
    except NotImplementedError:
        return None  # hardware not wired up yet; not a fault
    except Exception as exc:
        print(f"[sensor error] {sensor.name} ({sensor.basin_id}): {exc}")
        db.insert_fault(conn, sensor.basin_id, sensor.name, None, f"read error: {exc}", ts=ts)
        return None

    reason = validity.check(reading.basin_id, reading.sensor, reading.value, ts)
    if reason:
        print(f"[invalid] {reading.sensor} ({reading.basin_id}): {reason}")
        db.insert_fault(conn, reading.basin_id, reading.sensor, reading.value, reason, ts=ts)
        return None
    return reading.value


def read_all(conn, master_sensors, per_basin_sensors, fan_controllers, validity):
    """Read every sensor once and store one row per grow basin for this cycle.

    The master basin feeds every grow basin, so its values (pH, EC, water level) are read once
    and written into each basin's row.
    """
    cycle_ts = time.time()  # one timestamp for the whole cycle's row

    master_values = {sensor.name: _read_trusted(conn, validity, sensor) for sensor in master_sensors}

    for basin_id, sensors in per_basin_sensors.items():
        values = dict(master_values)
        for sensor in sensors:
            values[sensor.name] = _read_trusted(conn, validity, sensor)

        # Spec §4: never act on a reading that failed its checks. Holding the fan at its
        # current state is safer than driving it from a probe we know is lying.
        temperature = values.get("temperature")
        if temperature is not None:
            fan_controllers[basin_id].update(temperature)

        db.insert_cycle(conn, basin_id, values, ts=cycle_ts)


def sync_pending(conn):
    """Push unsynced cycles in batches until the queue drains (spec §8).

    A whole batch is marked synced on success, including rows with nothing to send (every
    value NULL). Those have nowhere to go, and leaving them unsynced would park them at the
    front of the oldest-first queue forever, eventually filling every batch.
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
    print(f"[startup] system_name={SYSTEM_NAME} (device {DEVICE_NAME}, id from {DEVICE_ID_SOURCE})")
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
