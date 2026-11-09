"""Sensors that exist once, on the shared reservoir: EC, pH, water level.

pH is an analog board on the shared ADS1115, water level is a GPIO input, and EC comes from a
Bluelab Guardian over the Edenic cloud API rather than from the Pi's own hardware.
"""

import statistics

from sensors.ads1115 import get_shared_adc
from sensors.base import Sensor, Reading
from sensors.edenic import EdenicTelemetry
from config import (
    EDENIC_DEVICE_ID,
    EDENIC_EC_KEY,
    MASTER_BASIN,
    PH_ADC_CHANNEL,
    PH_INTERCEPT,
    PH_SAMPLES_PER_READ,
    PH_SLOPE,
    WATER_LEVEL_GPIO_PIN,
)


class ECSensor(Sensor):
    """Bluelab Guardian EC, fetched from the Edenic cloud API rather than wired to the Pi.

    Edenic already reports mS/cm, which is what spec §5's setpoints and the remote `ec` column
    use, so no conversion is needed. The Guardian does its own temperature compensation.

    This is the one sensor whose reading depends on the internet; see sensors/edenic.py for
    why that matters and how a failed fetch is handled.
    """

    name = "ec"
    unit = "mS/cm"

    def __init__(self, device_id: str = EDENIC_DEVICE_ID):
        super().__init__(MASTER_BASIN)
        self.device_id = device_id
        self._telemetry = None

    def _get_telemetry(self):
        # Built on first read so constructing the sensor makes no network call.
        if self._telemetry is None:
            if not self.device_id:
                raise RuntimeError(
                    "EDENIC_DEVICE_ID not set — run list_edenic_devices.py and add it to .env"
                )
            self._telemetry = EdenicTelemetry(self.device_id)
        return self._telemetry

    def read(self) -> Reading:
        value = self._get_telemetry().value(EDENIC_EC_KEY)
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

            # pull_up=None disables the internal pull resistor. gpiozero defaults to a
            # pull-down, which sits in parallel with the external divider's lower leg and
            # drags the HIGH level toward the Pi's 2.31V threshold — enough to make a
            # correctly-sized divider read intermittently. The sensor drives both rails
            # itself, so no internal pull is wanted.
            self._device = DigitalInputDevice(self.pin, pull_up=None, active_state=True)
        return self._device

    def read(self) -> Reading:
        value = float(self._get_device().value)
        return Reading(basin_id=self.basin_id, sensor=self.name, value=value, unit=self.unit)
