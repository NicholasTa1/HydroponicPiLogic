"""Sensirion SCD41 driver (Adafruit 5190 breakout): CO2, air temperature, humidity.

One chip supplies all three measurements, so a single read is cached and served to the three
Sensor classes in environment.py. That is correctness rather than optimisation: the three
values must come from the same sample, and the chip only produces a new one every 5 seconds.

Command codes, CRC parameters and conversions are from the Sensirion SCD4x datasheet v1.7.
"""

from __future__ import annotations

import time

SCD4X_ADDRESS = 0x62        # fixed in silicon; see the multiplexer note in PROGRESS.md

_START_PERIODIC_MEASUREMENT = 0x21B1
_STOP_PERIODIC_MEASUREMENT = 0x3F86
_READ_MEASUREMENT = 0xEC05
_GET_DATA_READY_STATUS = 0xE4B8

_MEASUREMENT_INTERVAL_S = 5.0    # the chip's own update rate in periodic mode
_STOP_SETTLE_S = 0.5             # datasheet: ignores other commands for 500ms after stop


def _crc8(data: bytes) -> int:
    """CRC-8, polynomial 0x31, init 0xFF, no reflection, no final XOR."""
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def words_from_response(data: bytes) -> list[int]:
    """Split a response into 16-bit words, verifying the CRC byte that follows each one."""
    if len(data) % 3:
        raise ValueError(f"response length {len(data)} is not a whole number of word+CRC groups")

    words = []
    for i in range(0, len(data), 3):
        word_bytes = data[i : i + 2]
        if _crc8(word_bytes) != data[i + 2]:
            raise ValueError(f"CRC mismatch on word at byte {i}")
        words.append((word_bytes[0] << 8) | word_bytes[1])
    return words


def convert_measurement(words: list[int]) -> tuple[int, float, float]:
    """(co2_ppm, temperature_c, relative_humidity_pct) from the three read_measurement words."""
    co2, raw_temp, raw_rh = words
    return co2, -45.0 + 175.0 * raw_temp / 65536.0, 100.0 * raw_rh / 65536.0


class SCD4X:
    def __init__(self, address: int = SCD4X_ADDRESS, bus_number: int = 1):
        from smbus2 import SMBus  # Pi-only, imported at construction rather than module load

        self.address = address
        self.bus = SMBus(bus_number)
        self._cached = None
        self._cached_at = 0.0
        self._started = False

    def _command(self, command: int) -> None:
        from smbus2 import i2c_msg

        self.bus.i2c_rdwr(i2c_msg.write(self.address, [command >> 8, command & 0xFF]))

    def _read(self, command: int, length: int, delay_s: float = 0.001) -> bytes:
        from smbus2 import i2c_msg

        self._command(command)
        time.sleep(delay_s)
        message = i2c_msg.read(self.address, length)
        self.bus.i2c_rdwr(message)
        return bytes(message)

    def start(self) -> None:
        # Stop first: a sensor left in periodic mode by a previous run rejects start_periodic,
        # which otherwise looks like a wiring fault on every restart.
        self._command(_STOP_PERIODIC_MEASUREMENT)
        time.sleep(_STOP_SETTLE_S)
        self._command(_START_PERIODIC_MEASUREMENT)
        self._started = True

    def data_ready(self) -> bool:
        word = words_from_response(self._read(_GET_DATA_READY_STATUS, 3))[0]
        return bool(word & 0x07FF)   # datasheet: low 11 bits all zero means not ready

    def read(self) -> tuple[int, float, float]:
        """(co2_ppm, temperature_c, relative_humidity_pct), cached for one measurement interval."""
        now = time.monotonic()
        if self._cached is not None and now - self._cached_at < _MEASUREMENT_INTERVAL_S:
            return self._cached

        if not self._started:
            self.start()

        deadline = time.monotonic() + 2 * _MEASUREMENT_INTERVAL_S
        while not self.data_ready():
            if time.monotonic() > deadline:
                raise TimeoutError("SCD4x reported no measurement ready")
            time.sleep(0.5)

        self._cached = convert_measurement(words_from_response(self._read(_READ_MEASUREMENT, 9)))
        self._cached_at = time.monotonic()
        return self._cached

    def close(self):
        self.bus.close()


_shared_scd4x: SCD4X | None = None


def get_shared_scd4x() -> SCD4X:
    """One chip, one handle, shared by the CO2/temperature/humidity Sensor classes."""
    global _shared_scd4x
    if _shared_scd4x is None:
        _shared_scd4x = SCD4X()
    return _shared_scd4x
