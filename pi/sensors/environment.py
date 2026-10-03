"""Per-basin sensors: air temperature, water temperature, humidity, CO2, light.

Air temperature, humidity and CO2 all come from one Sensirion SCD41, so they share a single
cached read (see sensors/scd4x.py) and will always report from the same sample.

One instance of each class per basin_id in config.BASIN_IDS. Water temperature and light are
still stubs pending hardware.
"""

from sensors.base import Sensor, Reading
from sensors.scd4x import get_shared_scd4x


class TemperatureSensor(Sensor):
    """Ambient air temperature at the basin. Drives the fan feedback loop in control.py."""

    name = "temperature"
    unit = "C"

    def read(self) -> Reading:
        _, temperature_c, _ = get_shared_scd4x().read()
        return Reading(self.basin_id, self.name, temperature_c, self.unit)


class WaterTempSensor(Sensor):
    """Per-basin water temperature (DS18B20 or similar, 1-Wire)."""

    name = "water_temp"
    unit = "C"

    def read(self) -> Reading:
        # TODO: 1-Wire read, one probe per basin.
        raise NotImplementedError


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
    name = "light"
    unit = "lux"

    def read(self) -> Reading:
        # TODO: e.g. BH1750 over I2C.
        raise NotImplementedError
