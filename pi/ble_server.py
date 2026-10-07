"""BLE GATT peripheral serving recent readings to the phone when Wi-Fi is unavailable.

Runs as its own process (hydro-ble.service), separate from the control loop. They share only
the SQLite file, never imports, so a BLE crash cannot stop sensor logging and vice versa.

Read-only and history-only: there is no write path and no command path. The phone cannot
influence the control loop through this, which keeps spec §9's "BLE is explicitly not a
control path" intact even though the plan extends it from broadcast to request/response.

Requires `bless` (pip install bless) and a working BlueZ stack. Run:  python3 ble_server.py
"""

from __future__ import annotations

import asyncio
import logging
import socket

import ble_protocol as bp
import db
from config import (
    BLE_CONTROL_UUID,
    BLE_DATA_UUID,
    BLE_DEVICE_PREFIX,
    BLE_MAX_ROWS,
    BLE_NOTIFY_GAP_S,
    BLE_SERVICE_UUID,
    SAMPLE_INTERVAL_S,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ble")

# Readings within one control-loop pass land milliseconds apart; anything beyond half a
# sampling interval is a different cycle.
CYCLE_GAP_S = SAMPLE_INTERVAL_S / 2


def read_snapshots(wanted: int) -> list[str]:
    """Blocking database work. Called via asyncio.to_thread so it never stalls the BLE loop."""
    import time

    # Enough rows to cover the requested cycles even when every sensor reports.
    row_limit = max(wanted * 12, 60)
    conn = db.connect_readonly()
    try:
        rows = db.get_recent_readings(conn, row_limit)
    finally:
        conn.close()
    return bp.build_messages(rows, wanted, CYCLE_GAP_S, time.time())


class HydroBLEServer:
    def __init__(self):
        self._server = None
        self._busy = False
        self._loop = None

    async def start(self):
        from bless import BlessServer
        from bless import GATTCharacteristicProperties, GATTAttributePermissions

        self._loop = asyncio.get_running_loop()
        name = f"{BLE_DEVICE_PREFIX}-{socket.gethostname()}"
        self._server = BlessServer(name=name)
        # bless requires BOTH callbacks. Without the read one it raises "read callback is
        # undefined" the moment anything reads a characteristic, including a central probing
        # DATA before subscribing.
        self._server.read_request_func = self._on_read
        self._server.write_request_func = self._on_write

        await self._server.add_new_service(BLE_SERVICE_UUID)
        await self._server.add_new_characteristic(
            BLE_SERVICE_UUID,
            BLE_CONTROL_UUID,
            GATTCharacteristicProperties.write | GATTCharacteristicProperties.write_without_response,
            None,
            GATTAttributePermissions.writeable,
        )
        await self._server.add_new_characteristic(
            BLE_SERVICE_UUID,
            BLE_DATA_UUID,
            GATTCharacteristicProperties.notify | GATTCharacteristicProperties.read,
            None,
            GATTAttributePermissions.readable,
        )

        await self._server.start()
        log.info("advertising as %s, service %s", name, BLE_SERVICE_UUID)

    def _on_read(self, characteristic, **kwargs) -> bytes:
        """Reads just return the last value written to the characteristic.

        History is delivered by notification, not by reading DATA, so this exists to satisfy
        bless rather than to serve data.
        """
        log.info("read on %s", characteristic.uuid)
        return characteristic.value or b""

    def _on_write(self, characteristic, value, **kwargs):
        """Called synchronously by bless, so the real work is scheduled onto the loop."""
        # Logged before anything else: a write that arrives but does not match CONTROL used to
        # return silently, which is indistinguishable from the write never arriving at all.
        log.info("write on %s: %r", characteristic.uuid, bytes(value))

        if characteristic.uuid.lower() != BLE_CONTROL_UUID.lower():
            log.warning("write was not on CONTROL (%s), ignoring", BLE_CONTROL_UUID)
            return

        wanted = bp.parse_request(bytes(value))
        if wanted is None:
            log.warning("ignoring malformed control write: %r", bytes(value))
            self._notify(bp.error_message("bad request"))
            return

        if self._busy:
            # A double tap must not start a second database read mid-transfer.
            log.info("transfer already in progress, ignoring GET")
            return

        # run_coroutine_threadsafe rather than create_task: this callback is not guaranteed to
        # run on the loop thread, and create_task would fail there with no running loop.
        asyncio.run_coroutine_threadsafe(self._serve(min(wanted, BLE_MAX_ROWS)), self._loop)

    def _notify(self, message: str):
        self._server.get_characteristic(BLE_DATA_UUID).value = message.encode()
        self._server.update_value(BLE_SERVICE_UUID, BLE_DATA_UUID)

    async def _serve(self, wanted: int):
        self._busy = True
        try:
            try:
                messages = await asyncio.to_thread(read_snapshots, wanted)
            except Exception as exc:
                log.error("database read failed: %s", exc)
                self._notify(bp.error_message("db busy"))
                return

            too_big = bp.oversized(messages)
            if too_big:
                # Would be silently truncated by the MTU; say so rather than send corrupt data.
                log.error("%d message(s) exceed one notification", len(too_big))
                self._notify(bp.error_message("row too large"))
                return

            for message in messages:
                self._notify(message)
                await asyncio.sleep(BLE_NOTIFY_GAP_S)
            log.info("sent %d snapshot(s)", len(messages) - 2)
        finally:
            self._busy = False


async def main():
    server = HydroBLEServer()
    await server.start()
    await asyncio.Event().wait()   # advertise until the service is stopped


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
