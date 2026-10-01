"""Sensors that exist once, on the shared reservoir: EC, pH, water level.

EC and pH are both analog boards read through the shared ADS1115. Water level hardware is
still TBD (load cell vs ultrasonic) — read() is a stub until that part is picked.
"""

import statistics

from sensors.ads1115 import get_shared_adc
from sensors.base import Sensor, Reading
from config import (
    EC_ADC_CHANNEL,
    EC_SAMPLES_PER_READ,
    EC_VOLTS_TO_US_CM,
    MASTER_BASIN,
    PH_ADC_CHANNEL,
    PH_INTERCEPT,
    PH_SAMPLES_PER_READ,
    PH_SLOPE,
)


class ECSensor(Sensor):
    """SenseCAP S-EC-01 in analog mode, read through an ADS1115 channel.

    Reported in mS/cm to match the spec's setpoint table and the remote `ec` column, while the
    datasheet's conversion works in uS/cm. Temperature compensation happens inside the sensor,
    so there is nothing to correct for here.
    """

    name = "ec"
    unit = "mS/cm"

    def __init__(self, channel: int = EC_ADC_CHANNEL):
        super().__init__(MASTER_BASIN)
        self.channel = channel

    def read(self) -> Reading:
        adc = get_shared_adc()
        samples = [adc.read_voltage(self.channel) for _ in range(EC_SAMPLES_PER_READ)]
        volts = statistics.median(samples)
        value = EC_VOLTS_TO_US_CM * volts / 1000.0
        return Reading(basin_id=self.basin_id, sensor=self.name, value=value, unit=self.unit)


class PHSensor(Sensor):
    """DFRobot analog pH board (SEN0161/SEN0169) read through an ADS1115 channel.

    The board emits an analog voltage; pH is linear in that voltage. Working in volts rather
    than raw ADC counts keeps the conversion independent of the ADC's resolution, which is
    what DFRobot's FAQ warns about for non-Arduino controllers.
    """

    name = "ph"
    unit = "pH"

    def __init__(self, channel: int = PH_ADC_CHANNEL):
        super().__init__(MASTER_BASIN)
        self.channel = channel

    def read(self) -> Reading:
        adc = get_shared_adc()
        samples = [adc.read_voltage(self.channel) for _ in range(PH_SAMPLES_PER_READ)]
        volts = statistics.median(samples)
        value = PH_SLOPE * volts + PH_INTERCEPT
        return Reading(basin_id=self.basin_id, sensor=self.name, value=value, unit=self.unit)


class WaterLevelSensor(Sensor):
    name = "water_level"
    unit = "pct"

    def __init__(self):
        super().__init__(MASTER_BASIN)

    def read(self) -> Reading:
        # TODO: load cell (mass -> volume) or ultrasonic (distance -> volume) once hardware
        # is selected. See PI_CONTROL_SPEC.md open items.
        raise NotImplementedError
