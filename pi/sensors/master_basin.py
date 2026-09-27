"""Sensors that exist once, on the shared reservoir: EC, pH, water level.

EC/pH ride on Atlas Scientific EZO carrier boards over I2C. Water level hardware is still TBD
(load cell vs ultrasonic) — read() is a stub until that part is picked.
"""

import random

from sensors.base import Sensor, Reading
from config import EZO_EC_ADDRESS, EZO_PH_ADDRESS, MASTER_BASIN


class ECSensor(Sensor):
    name = "ec"
    unit = "mS/cm"

    def __init__(self, address: int = EZO_EC_ADDRESS):
        super().__init__(MASTER_BASIN)
        self.address = address

    def read(self) -> Reading:
        # TODO: I2C read/command cycle against the EZO-EC board, fed by current water temp
        # for temperature compensation (see water_temp.py).
        raise NotImplementedError

    def close(self):
        """No-op for now; future scope for the SMBus handle."""
        pass


class PHSensor(Sensor):
    name = "ph"
    unit = "pH"

    def __init__(self, address: int = EZO_PH_ADDRESS):
        super().__init__(MASTER_BASIN)
        self.address = address

    def read(self) -> Reading:
        # DUMMY DATA — no probe wired up yet. Swap this body for the real I2C read/command
        # cycle against the EZO-pH board (temp-compensated) once hardware is on the bench.
        value = round(random.uniform(5.5, 6.5), 2)
        return Reading(basin_id=self.basin_id, sensor=self.name, value=value, unit=self.unit)

    def close(self):
        """No-op for now; future scope for the SMBus handle."""
        pass


class WaterLevelSensor(Sensor):
    name = "water_level"
    unit = "pct"

    def __init__(self):
        super().__init__(MASTER_BASIN)

    def read(self) -> Reading:
        # TODO: load cell (mass -> volume) or ultrasonic (distance -> volume) once hardware
        # is selected. See PI_CONTROL_SPEC.md open items.
        raise NotImplementedError
