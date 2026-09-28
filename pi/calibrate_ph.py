"""Two-point pH calibration against standard buffer solutions.

Run on the Pi with the probe wired up:  python3 calibrate_ph.py
Prints PH_SLOPE / PH_INTERCEPT values to paste into config.py.

Rinse the probe with distilled water between buffers, or you carry one solution into the
next and skew the calibration.
"""

import statistics
import time

from config import ADS1115_ADDRESS, ADS1115_PGA, PH_ADC_CHANNEL
from sensors.ads1115 import ADS1115

_SAMPLES = 20
_SAMPLE_INTERVAL_S = 0.5


def read_buffer(adc: ADS1115, label: str) -> float:
    input(f"\nPut the probe in the {label} buffer, then press Enter to sample...")
    samples = []
    for _ in range(_SAMPLES):
        volts = adc.read_voltage(PH_ADC_CHANNEL)
        samples.append(volts)
        print(f"  {volts:.4f} V")
        time.sleep(_SAMPLE_INTERVAL_S)

    median = statistics.median(samples)
    spread = max(samples) - min(samples)
    print(f"median {median:.4f} V (spread {spread:.4f} V)")
    if spread > 0.05:
        print("  warning: readings are still drifting — let the probe settle and redo this step")
    return median


def main():
    adc = ADS1115(ADS1115_ADDRESS, pga=ADS1115_PGA)

    acid_ph = 4.00
    acid_volts = read_buffer(adc, f"pH {acid_ph:.2f} (acid)")

    alkali_ph = float(input("\npH of your alkaline buffer [9.18]: ") or 9.18)
    alkali_volts = read_buffer(adc, f"pH {alkali_ph:.2f} (alkaline)")

    if abs(acid_volts - alkali_volts) < 0.01:
        print("\nBoth buffers read the same voltage — the probe is not responding.")
        print("Check the BNC connection and that the board has 5V before retrying.")
        return

    slope = (acid_ph - alkali_ph) / (acid_volts - alkali_volts)
    # DFRobot's own sample sketch computes the intercept against the PREVIOUS slope, which is
    # a bug in their code; use the slope we just derived.
    intercept = acid_ph - slope * acid_volts

    print("\nPaste into config.py:\n")
    print(f"PH_SLOPE = {slope:.4f}")
    print(f"PH_INTERCEPT = {intercept:.4f}")

    adc.close()


if __name__ == "__main__":
    main()
