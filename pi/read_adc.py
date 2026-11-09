"""Live ADC readout for hardware bring-up:  python3 read_adc.py   (Ctrl-C to stop)

Shows the raw voltage on each analog channel next to what the current config converts it to,
so you can tell "the probe is not wired up" apart from "the conversion constants are wrong".

Also how to identify the EC unit's output range: in 1413 uS/cm calibration solution the
voltage should be 1.413V, 0.565V, 0.283V or 0.141V, corresponding to EC_VOLTS_TO_US_CM of
1000, 2500, 5000 or 10000 respectively.
"""

import time

from config import (
    EC_ADC_CHANNEL,
    EC_VOLTS_TO_US_CM,
    PH_ADC_CHANNEL,
    PH_INTERCEPT,
    PH_SLOPE,
)
from sensors.ads1115 import get_shared_adc


def main():
    adc = get_shared_adc()
    print("channel  volts     converted")
    while True:
        ph_volts = adc.read_voltage(PH_ADC_CHANNEL)
        ec_volts = adc.read_voltage(EC_ADC_CHANNEL)

        ph = PH_SLOPE * ph_volts + PH_INTERCEPT
        ec = EC_VOLTS_TO_US_CM * ec_volts / 1000.0

        print(f"A{PH_ADC_CHANNEL} pH    {ph_volts:6.4f} V   pH {ph:5.2f}")
        print(f"A{EC_ADC_CHANNEL} EC    {ec_volts:6.4f} V   {ec:6.3f} mS/cm")
        print()
        time.sleep(1.0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
