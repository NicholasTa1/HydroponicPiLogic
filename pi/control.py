"""Simple bang-bang feedback loops. Dosing logic is deliberately out of scope for this skeleton."""

from __future__ import annotations

import time

from config import (
    FAN_GPIO_PINS,
    FAN_OFF_TEMP_F,
    FAN_ON_TEMP_F,
    FAN_RELAY_ACTIVE_HIGH,
    FAN_STALE_READING_S,
)


class FanController:
    """One per basin: decides the fan state from air temperature, and drives its GPIO pin.

    Bang-bang with a hysteresis band rather than a single threshold, so a basin sitting right
    at the setpoint does not switch the fan every 30s cycle.

    All the fan's policy lives here, including what to do with a cycle that produced no
    trusted reading — see update(). The pin is an output to a MOSFET or relay, never to the
    fan itself; config.FAN_GPIO_PINS has the wiring constraints.
    """

    def __init__(self, basin_id: str, pin: int | None = None, active_high: bool = FAN_RELAY_ACTIVE_HIGH):
        self.basin_id = basin_id
        self.pin = FAN_GPIO_PINS.get(basin_id) if pin is None else pin
        self.active_high = active_high
        self.fan_on = False
        self._device = None
        self._last_trusted_at: float | None = None
        self._failsafe_announced = False

    def _get_device(self):
        # Built on first use so constructing a controller stays side-effect free off the Pi,
        # the same way the sensors are built. A basin with no pin configured still tracks its
        # state in software, which is what the off-Pi checks exercise.
        if self._device is None and self.pin is not None:
            from gpiozero import DigitalOutputDevice

            self._device = DigitalOutputDevice(
                self.pin, active_high=self.active_high, initial_value=self.fan_on
            )
        return self._device

    def _apply(self) -> None:
        device = self._get_device()
        if device is not None:
            # gpiozero's value is logical, so active_high=False inverts the pin for us.
            device.value = int(self.fan_on)

    def _set(self, fan_on: bool, reason: str) -> None:
        if fan_on != self.fan_on:
            print(f"[fan] {self.basin_id}: {'ON' if fan_on else 'OFF'} ({reason})")
        self.fan_on = fan_on
        self._apply()

    def update(self, temperature_c: float | None = None, now: float | None = None) -> bool:
        """Feed in this cycle's air temperature, or None if nothing trusted was read.

        Returns the fan's new on/off state. Readings are Celsius (what the SCD41 reports, and
        what the remote column stores) while the thresholds stay Fahrenheit, which is how they
        were specified.
        """
        now = time.monotonic() if now is None else now
        if self._last_trusted_at is None:
            self._last_trusted_at = now  # start the failsafe clock at the first cycle

        if temperature_c is None:
            return self._update_without_reading(now)

        self._last_trusted_at = now
        self._failsafe_announced = False

        temperature_f = temperature_c * 9.0 / 5.0 + 32.0
        if temperature_f > FAN_ON_TEMP_F:
            self._set(True, f"{temperature_f:.1f} F above {FAN_ON_TEMP_F:.0f} F")
        elif temperature_f < FAN_OFF_TEMP_F:
            self._set(False, f"{temperature_f:.1f} F below {FAN_OFF_TEMP_F:.0f} F")
        else:
            self._apply()  # inside the band: hold, but keep the pin matching our state
        return self.fan_on

    def _update_without_reading(self, now: float) -> bool:
        """No trusted temperature this cycle: hold briefly, then fail toward cooling.

        Spec §4 says never act on a reading that failed its checks, and holding the current
        state is right for a one-off glitch. It is wrong for a sensor that has died, because
        the hold lasts forever — and the two failure directions are not equal. A fan stuck off
        lets the crop cook; a fan stuck on costs some power and noise. So after
        FAN_STALE_READING_S the fan runs until a trusted reading says otherwise.
        """
        if now - self._last_trusted_at < FAN_STALE_READING_S:
            self._apply()
            return self.fan_on

        if not self._failsafe_announced:
            minutes = FAN_STALE_READING_S / 60
            print(f"[fan] {self.basin_id}: no trusted temperature for {minutes:.0f} min, running the fan")
            self._failsafe_announced = True
        self._set(True, "temperature unreadable")
        return self.fan_on
