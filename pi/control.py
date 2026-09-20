"""Simple bang-bang feedback loops. Dosing logic is deliberately out of scope for this skeleton."""

from config import FAN_OFF_TEMP_F, FAN_ON_TEMP_F


class FanController:
    """One per basin. Hysteresis band avoids chattering at the threshold."""

    def __init__(self, basin_id: str):
        self.basin_id = basin_id
        self.fan_on = False

    def update(self, temperature_f: float) -> bool:
        """Feed the latest basin temperature reading in; returns the fan's new on/off state."""
        if temperature_f > FAN_ON_TEMP_F:
            self.fan_on = True
        elif temperature_f < FAN_OFF_TEMP_F:
            self.fan_on = False
        # TODO: drive the actual relay/GPIO pin for this basin's fan.
        return self.fan_on
