"""Per-basin sensors: air temperature, water temperature, humidity, CO2, light.

One instance of each class per basin_id in config.BASIN_IDS. Hardware/interface for each is
still TBD — these are stubs to unblock the orchestration skeleton.
"""

from sensors.base import Sensor, Reading


class TemperatureSensor(Sensor):
    """Ambient air temperature at the basin. Drives the fan feedback loop in control.py."""

    name = "temperature"
    unit = "F"

    def read(self) -> Reading:
        # TODO: pick sensor (e.g. DHT22/SHT31) and wire up read.
        raise NotImplementedError


class WaterTempSensor(Sensor):
    """Per-basin water temperature (DS18B20 or similar, 1-Wire)."""

    name = "water_temp"
    unit = "F"

    def read(self) -> Reading:
        # TODO: 1-Wire read, one probe per basin.
        raise NotImplementedError


class HumiditySensor(Sensor):
    name = "humidity"
    unit = "pct"

    def read(self) -> Reading:
        # TODO: pick sensor (often bundled with temperature, e.g. DHT22/SHT31).
        raise NotImplementedError


class CO2Sensor(Sensor):
    name = "co2"
    unit = "ppm"

    def read(self) -> Reading:
        # TODO: e.g. MH-Z19 over UART, or SCD30/SCD40 over I2C.
        raise NotImplementedError


class LightSensor(Sensor):
    name = "light"
    unit = "lux"

    def read(self) -> Reading:
        # TODO: e.g. BH1750 over I2C.
        raise NotImplementedError
