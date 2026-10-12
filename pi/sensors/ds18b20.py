"""DS18B20 1-Wire temperature probe, read through the kernel's w1 sysfs interface.

No library needed: Linux already drives the 1-Wire bus and exposes each probe as a file. That
also means this works identically on Pi 4 and Pi 5, with nothing to break on a kernel update.

Requires 1-Wire enabled (`sudo raspi-config nonint do_onewire 0`, then reboot) and the 4.7k
pullup from DATA to VCC that ships with the probe.
"""

from __future__ import annotations

import glob

W1_DEVICE_GLOB = "/sys/bus/w1/devices/28-*"   # 28 is the DS18B20 family code

# The DS18B20's power-on reset value. Reading exactly this almost always means the probe lost
# power mid-conversion or the pullup is missing, rather than genuinely 85 degrees.
_POWER_ON_RESET_C = 85.0


def list_devices() -> list[str]:
    """Every DS18B20 the kernel can see, by its unique factory id."""
    return sorted(path.rsplit("/", 1)[-1] for path in glob.glob(W1_DEVICE_GLOB))


def read_temperature_c(device_id: str | None = None) -> float:
    """Read one probe. With no id, uses the only probe present.

    Raises rather than returning a suspect number: a bad CRC or a reset value is a failed
    reading, and the caller's error handling is a better place for that than the dataset.
    """
    if device_id is None:
        devices = list_devices()
        if not devices:
            raise RuntimeError(
                "no DS18B20 found — is 1-Wire enabled (raspi-config) and the 4.7k pullup fitted?"
            )
        if len(devices) > 1:
            raise RuntimeError(
                f"{len(devices)} DS18B20s present ({', '.join(devices)}); "
                "set WATER_TEMP_DEVICE_IDS in config.py to say which belongs to which basin"
            )
        device_id = devices[0]

    with open(f"/sys/bus/w1/devices/{device_id}/w1_slave") as handle:
        lines = handle.read().splitlines()

    if len(lines) < 2 or not lines[0].strip().endswith("YES"):
        raise ValueError(f"DS18B20 {device_id} reported a CRC failure")

    _, _, raw = lines[1].partition("t=")
    if not raw:
        raise ValueError(f"DS18B20 {device_id} returned no temperature field")

    celsius = int(raw) / 1000.0
    if celsius == _POWER_ON_RESET_C:
        raise ValueError(
            f"DS18B20 {device_id} returned its power-on reset value (85.0 C) — "
            "check the pullup resistor and the probe's power"
        )
    return celsius
