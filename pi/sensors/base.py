"""Common interface every sensor implements, so main.py can loop over them generically."""

from dataclasses import dataclass


@dataclass
class Reading:
    basin_id: str
    sensor: str
    value: float
    unit: str


class Sensor:
    """Subclass this for each physical sensor. name/unit identify the reading in storage."""

    name: str = "unnamed"
    unit: str = ""

    def __init__(self, basin_id: str):
        self.basin_id = basin_id

    def read(self) -> Reading:
        """Return one Reading. Raise on hardware/comm failure — do not return None/0 silently."""
        raise NotImplementedError
