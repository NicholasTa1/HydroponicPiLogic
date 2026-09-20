"""Orchestration loop: read every sensor every 30s, buffer in SQLite, sync+clear every 5 min.

Dosing/alarm/validity logic is intentionally left out of this skeleton — see PI_CONTROL_SPEC.md
for where that lands later. Outlier/glitch detection is handled off-Pi (time series forecasting
on the synced data), so nothing here filters or rejects readings before storage.
"""

import time

import db
import sync
from config import BASIN_IDS, SAMPLE_INTERVAL_S, SYNC_INTERVAL_S
from control import FanController
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


def read_all(conn, master_sensors, per_basin_sensors, fan_controllers):
    for sensor in master_sensors:
        try:
            db.insert_reading(conn, sensor.read())
        except NotImplementedError:
            pass  # hardware not wired up yet
        except Exception as exc:
            print(f"[sensor error] {sensor.name} ({sensor.basin_id}): {exc}")

    for basin_id, sensors in per_basin_sensors.items():
        for sensor in sensors:
            try:
                reading = sensor.read()
            except NotImplementedError:
                continue  # hardware not wired up yet
            except Exception as exc:
                print(f"[sensor error] {sensor.name} ({sensor.basin_id}): {exc}")
                continue

            db.insert_reading(conn, reading)
            if sensor.name == "temperature":
                fan_controllers[basin_id].update(reading.value)


def sync_and_clear(conn):
    readings = db.get_all_readings(conn)
    if sync.send_batch(readings):
        db.clear_readings(conn)
    else:
        print("[sync] batch failed, will retry next cycle")


def main():
    conn = db.connect()
    master_sensors, per_basin_sensors = build_sensors()
    fan_controllers = {basin_id: FanController(basin_id) for basin_id in BASIN_IDS}

    last_sync = time.monotonic()

    while True:
        loop_start = time.monotonic()

        read_all(conn, master_sensors, per_basin_sensors, fan_controllers)

        if time.monotonic() - last_sync >= SYNC_INTERVAL_S:
            sync_and_clear(conn)
            last_sync = time.monotonic()

        elapsed = time.monotonic() - loop_start
        time.sleep(max(0.0, SAMPLE_INTERVAL_S - elapsed))


if __name__ == "__main__":
    main()
