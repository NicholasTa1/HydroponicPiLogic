"""Sensors that exist once, on the shared reservoir: EC, pH, water level.

EC/pH ride on Atlas Scientific EZO carrier boards over I2C. Water level hardware is still TBD
(load cell vs ultrasonic) — read() is a stub until that part is picked.
"""

import statistics

from sensors.ads1115 import ADS1115
from sensors.base import Sensor, Reading
from config import (
    ADS1115_ADDRESS,
    ADS1115_PGA,
    EZO_EC_ADDRESS,
    MASTER_BASIN,
    PH_ADC_CHANNEL,
    PH_INTERCEPT,
    PH_SAMPLES_PER_READ,
    PH_SLOPE,
)


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
        self._adc = None

    def _get_adc(self) -> ADS1115:
        # Built on first read so constructing the sensor stays side-effect free (and possible
        # off the Pi, where smbus2 does not exist).
        if self._adc is None:
            self._adc = ADS1115(ADS1115_ADDRESS, pga=ADS1115_PGA)
        return self._adc

    def read(self) -> Reading:
        adc = self._get_adc()
        samples = [adc.read_voltage(self.channel) for _ in range(PH_SAMPLES_PER_READ)]
        volts = statistics.median(samples)
        value = PH_SLOPE * volts + PH_INTERCEPT
        return Reading(basin_id=self.basin_id, sensor=self.name, value=value, unit=self.unit)

    def close(self):
        if self._adc is not None:
            self._adc.close()
            self._adc = None


class WaterLevelSensor(Sensor):
    name = "water_level"
    unit = "pct"

    def __init__(self):
        super().__init__(MASTER_BASIN)

    def read(self) -> Reading:
        # TODO: load cell (mass -> volume) or ultrasonic (distance -> volume) once hardware
        # is selected. See PI_CONTROL_SPEC.md open items.
        raise NotImplementedError
