"""Switch the fan on and off from the command line, to check the wiring before trusting
the control loop.

Run on the Pi:  python3 test_fan.py [basin_id]

The fan should spin while this says ON and stop while it says OFF. If it does the opposite,
FAN_RELAY_ACTIVE_HIGH in config.py is set the wrong way round for your relay board.
"""

from __future__ import annotations

import sys
import time

from config import BASIN_IDS, FAN_GPIO_PINS
from control import FanController


def main():
    basin_id = sys.argv[1] if len(sys.argv) > 1 else BASIN_IDS[0]
    pin = FAN_GPIO_PINS.get(basin_id)
    if pin is None:
        print(f"No fan pin configured for {basin_id} — add it to FAN_GPIO_PINS in config.py.")
        return

    fan = FanController(basin_id)
    print(f"{basin_id}: fan on BCM {pin}. Ctrl-C to stop (the pin resets to off on exit).")

    try:
        while True:
            for state, seconds in ((True, 5), (False, 5)):
                print(f"  {'ON ' if state else 'OFF'} for {seconds}s")
                fan._set(state, "manual test")
                time.sleep(seconds)
    except KeyboardInterrupt:
        fan._set(False, "test ended")
        print("\nfan off.")


if __name__ == "__main__":
    main()
