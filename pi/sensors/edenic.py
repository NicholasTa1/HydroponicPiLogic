"""Edenic cloud API client, for reading a Bluelab Guardian's probe over the network.

Unlike every other sensor here, this one is not wired to the Pi — it reads values the Guardian
has already uploaded to Edenic. Two consequences worth being deliberate about:

- EC now depends on the internet. Spec §3 says the network is never in the control path, so
  dosing on an EC value fetched from a cloud API is a departure from that. A failed fetch
  raises, which the control loop records as a fault and leaves as NULL, so it degrades to "no
  reading" rather than a stale one.
- Edenic rate-limits to roughly one request per minute, while the control loop samples every
  30s. Responses are therefore cached for EDENIC_MIN_POLL_S and served from cache in between.

Endpoints and response shape are as used by the Home Assistant integration at
github.com/plumbobdev/homeassistant-edenic; Edenic publishes no official API documentation.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from config import (
    EDENIC_API_BASE_URL,
    EDENIC_API_KEY,
    EDENIC_MIN_POLL_S,
    EDENIC_ORGANIZATION_ID,
    EDENIC_REQUEST_TIMEOUT_S,
)

_REQUEST_TIMEOUT_S = EDENIC_REQUEST_TIMEOUT_S


def _get(path: str) -> dict | list:
    if not EDENIC_API_KEY:
        raise RuntimeError("EDENIC_API_KEY not set — add it to .env (see .env.example)")

    request = urllib.request.Request(
        f"{EDENIC_API_BASE_URL}{path}", headers={"Authorization": EDENIC_API_KEY}
    )
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_S) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        # The integration this was derived from treats 400 as the rate-limit response.
        if exc.code == 400:
            raise RuntimeError("Edenic rate limit — raise EDENIC_MIN_POLL_S") from exc
        raise RuntimeError(f"Edenic HTTP {exc.code}") from exc


def list_devices() -> list:
    """Every device on the organisation, for finding a device id."""
    if not EDENIC_ORGANIZATION_ID:
        raise RuntimeError("EDENIC_ORGANIZATION_ID not set — add it to .env")
    return _get(f"/device/{EDENIC_ORGANIZATION_ID}")


class EdenicTelemetry:
    """One device's latest telemetry, cached so the 30s loop cannot outrun the rate limit."""

    def __init__(self, device_id: str):
        self.device_id = device_id
        self._cached = None
        self._cached_at = 0.0

    def _telemetry(self) -> dict:
        now = time.monotonic()
        if self._cached is not None and now - self._cached_at < EDENIC_MIN_POLL_S:
            return self._cached

        self._cached = _get(f"/telemetry/{self.device_id}")
        self._cached_at = now
        return self._cached

    def value(self, key: str) -> float:
        """Latest value for one telemetry key, e.g. 'electrical_conductivity'.

        Values arrive as strings in a newest-first list, so they are converted here.
        """
        entries = self._telemetry().get(key)
        if not entries:
            raise ValueError(f"Edenic returned no {key!r} for device {self.device_id}")
        return float(entries[0]["value"])
