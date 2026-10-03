"""Poll every implemented sensor and print what it reports:  python3 read_sensors.py

Bring-up tool. Unlike main.py this never writes to SQLite or Supabase, and unlike read_adc.py
it covers the I2C sensors too, not just the ADC channels. Sensors that are still stubs or whose
hardware is missing report their error instead of taking the loop down.
"""

import time

from main import build_sensors

INTERVAL_S = 5.0


def main():
    master, per_basin = build_sensors()
    sensors = list(master) + [s for group in per_basin.values() for s in group]

    print("first SCD41 reading takes ~6s (it needs one 5s measurement cycle)\n")
    while True:
        for sensor in sensors:
            try:
                reading = sensor.read()
            except NotImplementedError:
                print(f"  {sensor.name:12s} {sensor.basin_id:8s} -- not implemented")
            except Exception as exc:
                print(f"  {sensor.name:12s} {sensor.basin_id:8s} !! {exc}")
            else:
                print(f"  {reading.sensor:12s} {reading.basin_id:8s} {reading.value:8.2f} {reading.unit}")
        print()
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
