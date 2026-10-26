"""Two-point pH calibration against standard buffer solutions (e.g. pH 4.00 and 7.00).

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
_STABLE_SPREAD_V = 0.01   # tighter than the old 0.05 warning: this now gates acceptance


def _sample(adc: ADS1115) -> tuple[float, float]:
    samples = []
    for _ in range(_SAMPLES):
        volts = adc.read_voltage(PH_ADC_CHANNEL)
        samples.append(volts)
        print(f"  {volts:.4f} V")
        time.sleep(_SAMPLE_INTERVAL_S)
    return statistics.median(samples), max(samples) - min(samples)


def read_buffer(adc: ADS1115, label: str) -> float:
    """Sample until the probe has actually settled, rather than after a fixed window.

    Near pH 7 the electrode sits at its isopotential point and can take minutes to stabilise,
    where pH 4 settles in seconds. A fixed window would quietly accept a drifting reading and
    skew the calibration, so this repeats until the spread is small or the operator accepts it.
    """
    input(f"\nPut the probe in the {label} buffer, then press Enter to sample...")

    while True:
        median, spread = _sample(adc)
        print(f"median {median:.4f} V (spread {spread:.4f} V)")

        if spread <= _STABLE_SPREAD_V:
            return median

        print(f"  still drifting (spread above {_STABLE_SPREAD_V} V).")
        print("  Near pH 7 this is normal and can take a few minutes.")
        if input("  press Enter to keep sampling, or type 'use' to accept anyway: ").strip().lower() == "use":
            return median


def main():
    adc = ADS1115(ADS1115_ADDRESS, pga=ADS1115_PGA)

    print("Two-point calibration. Any two buffers work; 4.00 and 7.00 are the common pair,")
    print("and they bracket this system's 5.4-6.2 target, so readings are interpolated.")
    print("Rinse the probe with distilled water between buffers.")

    first_ph = float(input("\npH of your FIRST buffer [4.00]: ") or 4.00)
    first_volts = read_buffer(adc, f"pH {first_ph:.2f}")

    second_ph = float(input("\npH of your SECOND buffer [7.00]: ") or 7.00)
    second_volts = read_buffer(adc, f"pH {second_ph:.2f}")

    if abs(first_ph - second_ph) < 1.0:
        print("\nThose two buffers are too close together to fit a reliable line.")
        return

    if abs(first_volts - second_volts) < 0.01:
        print("\nBoth buffers read the same voltage — the probe is not responding.")
        print("Check the BNC connection and that the board has 5V before retrying.")
        return

    slope = (first_ph - second_ph) / (first_volts - second_volts)
    # DFRobot's own sample sketch computes the intercept against the PREVIOUS slope, which is
    # a bug in their code; use the slope we just derived.
    intercept = first_ph - slope * first_volts

    print("\nPaste into config.py:\n")
    print(f"PH_SLOPE = {slope:.4f}")
    print(f"PH_INTERCEPT = {intercept:.4f}")

    adc.close()


if __name__ == "__main__":
    main()
