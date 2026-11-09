"""Minimal ADS1115 driver: single-shot, single-ended reads returning volts.

Drives the chip's registers directly instead of going through the Adafruit CircuitPython
library, which avoids both that library's API churn and Blinka's platform detection (which
is its own source of trouble on a Pi 5). The register map is fixed in silicon.
"""

from __future__ import annotations

import time

from config import ADS1115_ADDRESS, ADS1115_PGA

_CONVERSION_REGISTER = 0x00
_CONFIG_REGISTER = 0x01

_MUX_SINGLE_ENDED = {0: 0x4, 1: 0x5, 2: 0x6, 3: 0x7}

# PGA setting -> full scale voltage, from the ADS1115 datasheet's gain table.
_FULL_SCALE_VOLTS = {0: 6.144, 1: 4.096, 2: 2.048, 3: 1.024, 4: 0.512, 5: 0.256}

_CONVERSION_WAIT_S = 0.02   # a 128 SPS conversion takes ~7.8ms; the rest is margin


class ADS1115:
    def __init__(self, address: int, bus_number: int = 1, pga: int = 1):
        from smbus2 import SMBus  # Pi-only, so imported at construction rather than module load

        self.address = address
        self.pga = pga
        self.bus = SMBus(bus_number)

    def read_voltage(self, channel: int) -> float:
        config = (
            0x8000                                  # OS: begin a single conversion
            | (_MUX_SINGLE_ENDED[channel] << 12)
            | (self.pga << 9)
            | 0x0100                                # MODE: single shot
            | 0x0080                                # DR: 128 SPS
            | 0x0003                                # COMP_QUE: comparator disabled
        )
        self.bus.write_i2c_block_data(
            self.address, _CONFIG_REGISTER, [config >> 8, config & 0xFF]
        )
        time.sleep(_CONVERSION_WAIT_S)

        high, low = self.bus.read_i2c_block_data(self.address, _CONVERSION_REGISTER, 2)
        raw = (high << 8) | low
        if raw > 0x7FFF:
            raw -= 0x10000
        return raw * _FULL_SCALE_VOLTS[self.pga] / 32768.0

    def close(self):
        self.bus.close()


_shared_adc: ADS1115 | None = None


def get_shared_adc() -> ADS1115:
    """There is one physical ADC, so every analog sensor goes through one handle.

    Built on first use rather than at import so modules stay importable off the Pi.
    """
    global _shared_adc
    if _shared_adc is None:
        _shared_adc = ADS1115(ADS1115_ADDRESS, pga=ADS1115_PGA)
    return _shared_adc
