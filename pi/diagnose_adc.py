"""Decide whether an ADS1115 is actually functioning:  python3 diagnose_adc.py

Voltage readings alone cannot tell a damaged chip from a wiring fault. This checks the parts
separately: whether the chip accepts and returns configuration over I2C, whether the raw
conversion register changes at all, and what every channel reports.
"""

import time

from smbus2 import SMBus

from config import ADS1115_ADDRESS, ADS1115_PGA
from sensors.ads1115 import _FULL_SCALE_VOLTS, _MUX_SINGLE_ENDED

CONVERSION_REGISTER = 0x00
CONFIG_REGISTER = 0x01


def read_register(bus, register):
    high, low = bus.read_i2c_block_data(ADS1115_ADDRESS, register, 2)
    return (high << 8) | low


def to_volts(raw):
    if raw > 0x7FFF:
        raw -= 0x10000
    return raw * _FULL_SCALE_VOLTS[ADS1115_PGA] / 32768.0


def main():
    bus = SMBus(1)

    print("1. CONFIG REGISTER READBACK")
    print("   Proves whether the chip stores what we write. Garbage here means the chip or")
    print("   its power is bad, not the wiring to the analog inputs.\n")

    for channel in (0, 1):
        wanted = (
            0x8000 | (_MUX_SINGLE_ENDED[channel] << 12) | (ADS1115_PGA << 9)
            | 0x0100 | 0x0080 | 0x0003
        )
        bus.write_i2c_block_data(
            ADS1115_ADDRESS, CONFIG_REGISTER, [wanted >> 8, wanted & 0xFF]
        )
        time.sleep(0.05)
        got = read_register(bus, CONFIG_REGISTER)
        # The OS bit reads back as 1 when idle, so compare everything except bit 15.
        match = (got & 0x7FFF) == (wanted & 0x7FFF)
        print(f"   ch{channel}: wrote 0x{wanted:04X}  read 0x{got:04X}  "
              f"{'MATCH' if match else 'MISMATCH'}")

    print("\n2. RAW CONVERSIONS ON EACH CHANNEL")
    print("   Ten reads per channel. A floating input wanders; a tied input should barely move.\n")

    for channel in range(4):
        config = (
            0x8000 | (_MUX_SINGLE_ENDED[channel] << 12) | (ADS1115_PGA << 9)
            | 0x0100 | 0x0080 | 0x0003
        )
        values = []
        for _ in range(10):
            bus.write_i2c_block_data(
                ADS1115_ADDRESS, CONFIG_REGISTER, [config >> 8, config & 0xFF]
            )
            time.sleep(0.02)
            values.append(read_register(bus, CONVERSION_REGISTER))

        volts = [to_volts(v) for v in values]
        spread = max(volts) - min(volts)
        print(f"   A{channel}: {min(volts):+.4f} to {max(volts):+.4f} V  "
              f"spread {spread:.4f} V   raw first/last 0x{values[0]:04X}/0x{values[-1]:04X}")

    print("\nWhat it means:")
    print("  CONFIG MISMATCH            -> chip or its power is faulty")
    print("  CONFIG matches, all 4 swing-> analog front end damaged, or GND not shared")
    print("  CONFIG matches, tied pin")
    print("    steady, others swing     -> chip is fine; the others are just floating (normal)")

    bus.close()


if __name__ == "__main__":
    main()
