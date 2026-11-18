"""Compare the DFRobot pH probe against the Bluelab Guardian's, in the same reservoir.

Testing only. Nothing in main.py, sync.py or the BLE path imports this, and it writes to its
own CSV rather than hydro.db, so it cannot affect the recorded dataset.

    python3 compare_ph.py            one comparison, now
    python3 compare_ph.py --watch    keep comparing every 60s, logging each pair
    python3 compare_ph.py --fit      fit PH_SLOPE/PH_INTERCEPT from the logged pairs

Why this exists: calibrate_ph.py against buffer solutions produced a span of about 40 mV/pH,
and we never settled whether that is ~67% of a buffered board's nominal (a tired but usable
electrode) or ~14% of an amplified board's (a dead one). The Guardian measures the same water
independently, so it can act as the reference the buffers could not.

--fit is the useful part. It needs pairs taken at two or more genuinely different pH values,
which means letting the reservoir drift or dosing it between runs -- a slope cannot be fitted
from readings all taken at one pH, however many there are. Calibrating against the Guardian
this way sidesteps the buffers entirely.
"""

from __future__ import annotations

import csv
import statistics
import sys
import time
from pathlib import Path

from config import (
    ADS1115_ADDRESS,
    ADS1115_PGA,
    EDENIC_DEVICE_ID,
    PH_ADC_CHANNEL,
    PH_INTERCEPT,
    PH_SAMPLES_PER_READ,
    PH_SLOPE,
)
from sensors.ads1115 import ADS1115
from sensors.edenic import EdenicTelemetry

# The Guardian publishes pH under this key, alongside the EC the control loop reads. Kept
# here rather than in config.py because nothing in the main path uses it.
GUARDIAN_PH_KEY = "ph"

LOG_PATH = Path("ph_compare.csv")
WATCH_INTERVAL_S = 60   # the Guardian publishes once a minute; faster just re-reads the cache
MIN_PH_SPREAD = 1.0     # pH range the logged pairs must cover before a slope means anything


def read_dfrobot(adc: ADS1115) -> tuple[float, float]:
    """(volts, pH) from the analog board, using the constants currently in config.py."""
    samples = [adc.read_voltage(PH_ADC_CHANNEL) for _ in range(PH_SAMPLES_PER_READ)]
    volts = statistics.median(samples)
    return volts, PH_SLOPE * volts + PH_INTERCEPT


def compare_once(adc: ADS1115, telemetry: EdenicTelemetry) -> tuple[float, float, float]:
    volts, dfrobot_ph = read_dfrobot(adc)
    guardian_ph = telemetry.value(GUARDIAN_PH_KEY)
    return volts, dfrobot_ph, guardian_ph


def log_pair(volts: float, dfrobot_ph: float, guardian_ph: float) -> None:
    new = not LOG_PATH.exists()
    with LOG_PATH.open("a", newline="") as handle:
        writer = csv.writer(handle)
        if new:
            writer.writerow(["ts", "volts", "dfrobot_ph", "guardian_ph"])
        writer.writerow([f"{time.time():.0f}", f"{volts:.4f}", f"{dfrobot_ph:.3f}", f"{guardian_ph:.3f}"])


def report(volts: float, dfrobot_ph: float, guardian_ph: float) -> None:
    difference = dfrobot_ph - guardian_ph
    print(f"  DFRobot  {dfrobot_ph:6.2f} pH   ({volts:.4f} V)")
    print(f"  Guardian {guardian_ph:6.2f} pH")
    print(f"  difference {difference:+.2f} pH")

    if abs(difference) <= 0.3:
        print("  -> agree. The constants in config.py are about right.")
        return

    # One reference point cannot separate a wrong slope from a wrong offset, but it can say
    # what intercept would reconcile them if the slope is assumed correct.
    implied = guardian_ph - PH_SLOPE * volts
    print(f"  -> disagree. Keeping PH_SLOPE = {PH_SLOPE:.4f}, the intercept that would match")
    print(f"     this reading is {implied:.4f} (config.py has {PH_INTERCEPT:.4f}).")
    print("     That only fixes the offset. Run --fit over pairs at two different pH values")
    print("     to find out whether the slope itself is wrong.")


def fit() -> None:
    """Least-squares fit of Guardian pH against DFRobot volts over every logged pair."""
    if not LOG_PATH.exists():
        print(f"No {LOG_PATH} yet — run --watch first.")
        return

    with LOG_PATH.open() as handle:
        rows = [(float(r["volts"]), float(r["guardian_ph"])) for r in csv.DictReader(handle)]

    if len(rows) < 2:
        print(f"Only {len(rows)} pair(s) logged; need at least 2.")
        return

    spread = max(ph for _, ph in rows) - min(ph for _, ph in rows)
    print(f"{len(rows)} pairs, Guardian pH spanning {spread:.2f} units")
    if spread < MIN_PH_SPREAD:
        print(f"That is under {MIN_PH_SPREAD} pH. A slope fitted over this little range is")
        print("mostly noise — let the reservoir drift or dose it, then log more pairs.")
        return

    n = len(rows)
    mean_v = sum(v for v, _ in rows) / n
    mean_ph = sum(ph for _, ph in rows) / n
    denominator = sum((v - mean_v) ** 2 for v, _ in rows)
    if denominator == 0:
        print("Every pair has the same voltage — the probe is not responding.")
        return

    slope = sum((v - mean_v) * (ph - mean_ph) for v, ph in rows) / denominator
    intercept = mean_ph - slope * mean_v
    residuals = [ph - (slope * v + intercept) for v, ph in rows]
    worst = max(abs(r) for r in residuals)

    # Volts per pH is 1/slope; the pH range the pairs covered does not enter into it.
    print(f"\n  {1000 / abs(slope):.0f} mV/pH  (a bare glass electrode gives 59)")
    print(f"  worst residual {worst:.2f} pH")
    print("\nFitted against the Guardian — paste into config.py if you trust it:\n")
    print(f"PH_SLOPE = {slope:.4f}")
    print(f"PH_INTERCEPT = {intercept:.4f}")


def main():
    if "--fit" in sys.argv:
        fit()
        return

    adc = ADS1115(ADS1115_ADDRESS, pga=ADS1115_PGA)
    telemetry = EdenicTelemetry(EDENIC_DEVICE_ID)
    watching = "--watch" in sys.argv

    try:
        while True:
            print(f"\n[{time.strftime('%H:%M:%S')}]")
            try:
                volts, dfrobot_ph, guardian_ph = compare_once(adc, telemetry)
            except Exception as exc:
                print(f"  comparison failed: {exc}")
            else:
                report(volts, dfrobot_ph, guardian_ph)
                if watching:
                    log_pair(volts, dfrobot_ph, guardian_ph)

            if not watching:
                return
            time.sleep(WATCH_INTERVAL_S)
    except KeyboardInterrupt:
        print(f"\nStopped. {LOG_PATH} holds the pairs; run --fit when they span a pH unit or more.")
    finally:
        adc.close()


if __name__ == "__main__":
    main()
