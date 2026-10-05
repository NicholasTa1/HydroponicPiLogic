"""Wire format for the BLE history transfer. Pure functions, no BLE and no database.

Kept separate from ble_server.py so the part most likely to be wrong — pivoting readings and
framing messages — can be tested without a radio or a Pi.

The local database stores one row per individual reading (long format). The app expects the
same wide snapshot shape it already gets from Supabase, so readings are pivoted here: one
message per sampling cycle, carrying every sensor read in that cycle.

See docs/ble-protocol.md for the contract the app implements against.
"""

from __future__ import annotations

import datetime
import json

from config import BLE_STALE_AFTER_S, REMOTE_COLUMNS

# Column order is fixed and part of the contract: the app reads values positionally.
COLUMNS = ["recorded_at", "ph", "ec", "temperature_c", "humidity", "light_intensity", "co2"]

# A conservative ceiling for one notification at the negotiated 517-byte MTU. Messages are far
# smaller than this in practice; exceeding it means the contract needs chunking, so it is
# surfaced rather than silently truncated.
MAX_MESSAGE_BYTES = 500


def _iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat()


def group_into_cycles(rows, gap_s: float) -> list[list]:
    """Split readings into sampling cycles, newest cycle first.

    Rows arrive newest-first. Readings taken in one pass of the control loop land milliseconds
    apart, so a gap materially larger than that marks a cycle boundary. Grouping by proximity
    rather than by rounding to a fixed interval keeps this correct when a cycle straddles an
    interval boundary or the loop runs late.
    """
    cycles: list[list] = []
    current: list = []
    previous_ts = None

    for row in rows:
        ts = row["ts"]
        if previous_ts is not None and abs(previous_ts - ts) > gap_s:
            cycles.append(current)
            current = []
        current.append(row)
        previous_ts = ts

    if current:
        cycles.append(current)
    return cycles


def snapshot(cycle) -> dict:
    """Collapse one cycle's readings into a single wide record keyed by app column names."""
    record = {column: None for column in COLUMNS}
    record["recorded_at"] = _iso(max(row["ts"] for row in cycle))
    for row in cycle:
        column = REMOTE_COLUMNS.get(row["sensor"])
        if column is not None:
            record[column] = row["value"]
    return record


def build_messages(rows, wanted: int, gap_s: float, now: float) -> list[str]:
    """Header, one message per snapshot, then an end marker — ready to notify in order."""
    cycles = group_into_cycles(rows, gap_s)[:wanted]
    snapshots = [snapshot(cycle) for cycle in cycles]

    newest_ts = max((row["ts"] for row in rows), default=None)
    sensors_ok = newest_ts is not None and (now - newest_ts) <= BLE_STALE_AFTER_S

    messages = [
        json.dumps(
            {"t": "hdr", "cols": COLUMNS, "n": len(snapshots), "sensors_ok": sensors_ok},
            separators=(",", ":"),
        )
    ]
    for index, record in enumerate(snapshots):
        messages.append(
            json.dumps(
                {"t": "row", "i": index, "v": [record[column] for column in COLUMNS]},
                separators=(",", ":"),
            )
        )
    messages.append(json.dumps({"t": "end"}, separators=(",", ":")))
    return messages


def error_message(reason: str) -> str:
    return json.dumps({"t": "err", "msg": reason}, separators=(",", ":"))


def oversized(messages: list[str]) -> list[str]:
    """Messages too large for one notification. Non-empty means the contract needs chunking."""
    return [m for m in messages if len(m.encode()) > MAX_MESSAGE_BYTES]


def parse_request(payload: bytes) -> int | None:
    """Parse a CONTROL write. 'GET 10' -> 10. Returns None if it is not a valid request."""
    try:
        text = payload.decode().strip().upper()
    except UnicodeDecodeError:
        return None

    parts = text.split()
    if len(parts) != 2 or parts[0] != "GET":
        return None
    try:
        count = int(parts[1])
    except ValueError:
        return None
    return count if count > 0 else None
