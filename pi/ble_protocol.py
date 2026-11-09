"""Wire format for the BLE history transfer. Pure functions, no BLE and no database.

Kept separate from ble_server.py so the part most likely to be wrong — pivoting readings and
framing messages — can be tested without a radio or a Pi.

The local database stores one wide row per sampling cycle, which is the same snapshot shape
the app already gets from Supabase, so each row becomes one message after renaming columns.

See docs/ble-protocol.md for the contract the app implements against.
"""

from __future__ import annotations

import datetime
import json

from config import BLE_STALE_AFTER_S, REMOTE_COLUMNS, remote_value

# Column order is fixed and part of the contract: the app reads values positionally.
# New columns go on the end so existing positions never move.
COLUMNS = [
    "recorded_at", "ph", "ec", "temperature_c", "humidity", "light_intensity", "co2", "water_temp",
    "water_level",
]

# A conservative ceiling for one notification at the negotiated 517-byte MTU. Messages are far
# smaller than this in practice; exceeding it means the contract needs chunking, so it is
# surfaced rather than silently truncated.
MAX_MESSAGE_BYTES = 500


def _iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat()


def snapshot(row) -> dict:
    """Turn one local cycle row into a record keyed by app column names."""
    record = {column: None for column in COLUMNS}
    record["recorded_at"] = _iso(row["ts"])
    for local, remote in REMOTE_COLUMNS.items():
        if remote in record:
            record[remote] = remote_value(local, row[local])
    return record


def build_messages(rows, wanted: int, now: float) -> list[str]:
    """Header, one message per snapshot, then an end marker — ready to notify in order.

    `rows` are cycle rows, newest first.
    """
    snapshots = [snapshot(row) for row in rows[:wanted]]

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
