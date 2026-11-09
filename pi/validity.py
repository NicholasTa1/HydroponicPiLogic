"""Sensor validity checks (spec §4), run on every reading before it is trusted.

A failed check means a broken probe, not an emergency: the reading is still stored, but it is
flagged, kept out of control decisions, and never allowed to trigger dosing. Spec §4 is explicit
that the system should alarm rather than act on a reading it cannot vouch for.

Pure except for the small amount of per-sensor history that rate-of-change and stuck detection
require, which is why this is testable without any hardware.
"""

from __future__ import annotations

from config import STUCK_READING_COUNT, STUCK_VALUE_DECIMALS, VALIDITY_RULES


class SensorValidity:
    """Tracks one sensor's history so successive readings can be judged against each other."""

    def __init__(self, sensor: str):
        self.sensor = sensor
        self.rules = VALIDITY_RULES.get(sensor, {})
        self._last_value = None
        self._last_ts = None
        self._repeat_count = 0

    def check(self, value: float, ts: float) -> str | None:
        """Return None if the reading is trustworthy, else a short reason it is not."""
        reason = self._range_failure(value) or self._rate_failure(value, ts) or self._stuck_failure(value)

        self._last_value = value
        self._last_ts = ts
        return reason

    def _range_failure(self, value: float) -> str | None:
        low, high = self.rules.get("min"), self.rules.get("max")
        if low is not None and value < low:
            return f"below range ({value:.4g} < {low})"
        if high is not None and value > high:
            return f"above range ({value:.4g} > {high})"
        return None

    def _rate_failure(self, value: float, ts: float) -> str | None:
        limit = self.rules.get("max_change_per_s")
        if limit is None or self._last_value is None:
            return None

        elapsed = ts - self._last_ts
        if elapsed <= 0:
            return None

        rate = abs(value - self._last_value) / elapsed
        if rate > limit:
            return f"changing too fast ({rate:.3g}/s > {limit}/s)"
        return None

    def _stuck_failure(self, value: float) -> str | None:
        """A probe repeating one value exactly is almost always dead, not stable.

        Skipped for sensors whose readings are legitimately constant, such as the water level
        detector, which only ever reports 0 or 1.
        """
        if not self.rules.get("stuck_check", True):
            return None

        rounded = round(value, STUCK_VALUE_DECIMALS)
        if self._last_value is not None and rounded == round(self._last_value, STUCK_VALUE_DECIMALS):
            self._repeat_count += 1
        else:
            self._repeat_count = 1

        if self._repeat_count >= STUCK_READING_COUNT:
            return f"stuck at {rounded} for {self._repeat_count} reads"
        return None


class ValidityTracker:
    """One SensorValidity per sensor per basin, created on demand."""

    def __init__(self):
        self._checkers: dict[tuple[str, str], SensorValidity] = {}

    def check(self, basin_id: str, sensor: str, value: float, ts: float) -> str | None:
        key = (basin_id, sensor)
        if key not in self._checkers:
            self._checkers[key] = SensorValidity(sensor)
        return self._checkers[key].check(value, ts)
