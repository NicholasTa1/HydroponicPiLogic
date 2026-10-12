"""Per-basin sensors: air temperature, water temperature, humidity, CO2, light.

Air temperature, humidity and CO2 all come from one Sensirion SCD41, so they share a single
cached read (see sensors/scd4x.py) and will always report from the same sample.

One instance of each class per basin_id in config.BASIN_IDS. Water temperature and light are
still stubs pending hardware.
"""

from config import VEML7700_GAIN, VEML7700_INTEGRATION_MS, WATER_TEMP_DEVICE_IDS
from sensors.base import Sensor, Reading
from sensors.ds18b20 import read_temperature_c
from sensors.scd4x import get_shared_scd4x


class TemperatureSensor(Sensor):
    """Ambient air temperature at the basin. Drives the fan feedback loop in control.py."""

    name = "temperature"
    unit = "C"

    def read(self) -> Reading:
        _, temperature_c, _ = get_shared_scd4x().read()
        return Reading(self.basin_id, self.name, temperature_c, self.unit)


class WaterTempSensor(Sensor):
    """Per-basin water temperature (DS18B20, 1-Wire).

    Each probe carries a unique factory id, so several can share one GPIO pin — which is how
    multiple basins will work. With a single probe the id can be left unconfigured.
    """

    name = "water_temp"
    unit = "C"

    def read(self) -> Reading:
        celsius = read_temperature_c(WATER_TEMP_DEVICE_IDS.get(self.basin_id))
        return Reading(self.basin_id, self.name, celsius, self.unit)


class HumiditySensor(Sensor):
    name = "humidity"
    unit = "pct"

    def read(self) -> Reading:
        _, _, relative_humidity = get_shared_scd4x().read()
        return Reading(self.basin_id, self.name, relative_humidity, self.unit)


class CO2Sensor(Sensor):
    name = "co2"
    unit = "ppm"

    def read(self) -> Reading:
        co2, _, _ = get_shared_scd4x().read()
        return Reading(self.basin_id, self.name, float(co2), self.unit)


class LightSensor(Sensor):
    """Adafruit VEML7700 on I2C.

    Its address (0x10) is fixed, so like the SCD41 only one can sit on a bus — multi-basin
    light sensing needs an I2C multiplexer.
    """

    name = "light"
    unit = "lux"

    def __init__(self, basin_id: str):
        super().__init__(basin_id)
        self._device = None

    def _get_device(self):
        # Built on first read so constructing the sensor stays side-effect free off the Pi.
        if self._device is None:
            from sensors.veml7700 import VEML7700

            self._device = VEML7700(
                gain=VEML7700_GAIN, integration_ms=VEML7700_INTEGRATION_MS
            )
        return self._device

    def read(self) -> Reading:
        return Reading(self.basin_id, self.name, self._get_device().read_lux(), self.unit)
