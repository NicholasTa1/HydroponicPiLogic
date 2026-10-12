"""Vishay VEML7700 ambient light sensor over I2C, driven at register level.

Consistent with the ADS1115 and SCD41 drivers: the register map is fixed in silicon, so this
avoids CircuitPython/Blinka entirely.

Unlike the SCD4x, the VEML7700 transfers 16-bit values little-endian, which is what smbus2's
word operations already do — so no byte swapping here.
"""

from __future__ import annotations

VEML7700_ADDRESS = 0x10     # fixed, not selectable

_ALS_CONF = 0x00
_ALS_DATA = 0x04

# ALS_CONF bits 12:11. Note the ordering is not monotonic — 1/8 and 1/4 sit above the x1/x2
# codes, which is easy to get wrong when writing this from the datasheet table.
_GAIN_BITS = {1: 0b00, 2: 0b01, 0.125: 0b10, 0.25: 0b11}

# ALS_CONF bits 9:6.
_INTEGRATION_BITS = {25: 0b1100, 50: 0b1000, 100: 0b0000, 200: 0b0001, 400: 0b0010, 800: 0b0011}

# Resolution at gain 2 / 800ms, from which every other combination scales.
_BASE_RESOLUTION = 0.0036

_SATURATED = 0xFFFF

# The Vishay application note characterises its non-linearity correction at gain 1/8 with a
# 100ms integration time, for raw counts above 100. Outside that operating point the 4th-order
# polynomial is extrapolating: at 20k lux it returns +269%, which is divergence rather than
# correction. So it is applied only where it was characterised, never generally.
_CORRECTION_GAIN = 0.125
_CORRECTION_INTEGRATION_MS = 100
_CORRECTION_MIN_RAW = 100

# The guide's own advice is to keep raw counts between 100 and 10000. Past the top of that the
# correction is no longer trustworthy, so a reading there is refused rather than reported.
_MAX_CHARACTERISED_RAW = 10000


def resolution(gain: float, integration_ms: int) -> float:
    """Lux per count for a gain/integration pair."""
    return _BASE_RESOLUTION * (2.0 / gain) * (800.0 / integration_ms)


def correct_nonlinearity(lux: float) -> float:
    """Vishay's 4th-order correction. Only valid at the characterised operating point."""
    return (
        6.0135e-13 * lux**4
        - 9.3924e-9 * lux**3
        + 8.1488e-5 * lux**2
        + 1.0023 * lux
    )


def _at_characterised_point(gain: float, integration_ms: int) -> bool:
    return gain == _CORRECTION_GAIN and integration_ms == _CORRECTION_INTEGRATION_MS


def raw_to_lux(raw: int, gain: float, integration_ms: int) -> float:
    lux = raw * resolution(gain, integration_ms)
    if _at_characterised_point(gain, integration_ms) and raw > _CORRECTION_MIN_RAW:
        return correct_nonlinearity(lux)
    return lux


class VEML7700:
    def __init__(
        self,
        address: int = VEML7700_ADDRESS,
        bus_number: int = 1,
        gain: float = 0.125,
        integration_ms: int = 100,
    ):
        from smbus2 import SMBus  # Pi-only, imported at construction rather than module load

        if gain not in _GAIN_BITS:
            raise ValueError(f"gain must be one of {sorted(_GAIN_BITS)}, got {gain}")
        if integration_ms not in _INTEGRATION_BITS:
            raise ValueError(
                f"integration_ms must be one of {sorted(_INTEGRATION_BITS)}, got {integration_ms}"
            )

        self.address = address
        self.gain = gain
        self.integration_ms = integration_ms
        self.bus = SMBus(bus_number)
        self._configure()

    def _configure(self):
        config = (_GAIN_BITS[self.gain] << 11) | (_INTEGRATION_BITS[self.integration_ms] << 6)
        # Bit 0 left clear: 0 powers the sensor on, 1 shuts it down.
        self.bus.write_word_data(self.address, _ALS_CONF, config)

    def read_raw(self) -> int:
        return self.bus.read_word_data(self.address, _ALS_DATA)

    def read_lux(self) -> float:
        raw = self.read_raw()
        if raw >= _SATURATED:
            raise ValueError(
                f"VEML7700 saturated at gain {self.gain} / {self.integration_ms}ms — "
                "lower the gain or the integration time in config.py"
            )
        if _at_characterised_point(self.gain, self.integration_ms) and raw > _MAX_CHARACTERISED_RAW:
            # Reporting this would mean extrapolating the correction well past its fit, which
            # produces a confident, badly wrong number. Refusing is the honest answer.
            raise ValueError(
                f"VEML7700 raw count {raw} is above the characterised range "
                f"({_MAX_CHARACTERISED_RAW}) — reduce VEML7700_INTEGRATION_MS to 25 in config.py"
            )
        return raw_to_lux(raw, self.gain, self.integration_ms)

    def close(self):
        self.bus.close()
