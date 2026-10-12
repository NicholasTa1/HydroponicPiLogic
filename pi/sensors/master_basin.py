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
    WATER_LEVEL_GPIO_PIN,
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
    """DFRobot SEN0204 (XKC-Y25-T12V) non-contact detector on a GPIO input.

    Reports 1 when liquid is present at the height the probe is mounted at, 0 when it is not.
    Deliberately NOT reported as a percentage: this is a point detector, not a gauge, and
    dressing a binary up as "0%" or "100%" would feed the dosing logic a number that looks
    continuous but is not. Spec §5 wants a real percentage; see PROGRESS.md for the gap.
    """

    name = "water_level"
    unit = "bool"

    def __init__(self, pin: int = WATER_LEVEL_GPIO_PIN):
        super().__init__(MASTER_BASIN)
        self.pin = pin
        self._device = None

    def _get_device(self):
        # Built on first read so constructing the sensor stays side-effect free off the Pi.
        if self._device is None:
            from gpiozero import DigitalInputDevice

            self._device = DigitalInputDevice(self.pin)
        return self._device

    def read(self) -> Reading:
        value = float(self._get_device().value)
        return Reading(basin_id=self.basin_id, sensor=self.name, value=value, unit=self.unit)
