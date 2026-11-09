# Plan: BLE reading in the React Native app

App-side work to read sensor history from the Raspberry Pi over BLE and show it to the user as
a table, for when Supabase is unreachable.

**The Pi side is done and tested.** It advertises, serves `GET <n>`, and a real transfer has
been verified end to end with nRF Connect on an Android phone. This plan covers only the app.

The full contract lives in `ble-protocol.md` in the Pi repo. Copy it across so both sides have
it — most BLE bugs come from the two drifting apart. Everything needed to start is repeated
below, so the plan stands alone until then.

---

## What is already true (verified on hardware, not assumed)

| | |
|---|---|
| Advertised name | `HydroPi-<hostname>`, e.g. `HydroPi-homegrow` |
| Service UUID | `6e3a1f80-5c21-4a7e-9d1b-2f8c4a0e7b31` |
| CONTROL characteristic | `6e3a1f81-5c21-4a7e-9d1b-2f8c4a0e7b31` — WRITE, WRITE NO RESPONSE |
| DATA characteristic | `6e3a1f82-5c21-4a7e-9d1b-2f8c4a0e7b31` — NOTIFY, READ |
| `GET 10` returns | 12 notifications: 1 header + 10 rows + 1 end marker |
| Message size | ~120 bytes, far below the 517-byte MTU |

### Message format

```json
{"t":"hdr","cols":["recorded_at","ph","ec","temperature_c","humidity","light_intensity","co2"],"n":10,"sensors_ok":true}
{"t":"row","i":0,"v":["2026-10-07T18:50:48+00:00",5.93,1.17,22.02,60.61,null,821.68]}
{"t":"end"}
{"t":"err","msg":"db busy"}
```

- `v` is positional and always matches `cols` in length and order.
- `i` runs `0 .. n-1`; rows are **newest first**.
- `n` may be less than requested, including `0`.
- Any value may be `null`.

| Column | Unit | Note |
|---|---|---|
| `recorded_at` | ISO 8601 UTC, offset-aware | |
| `ph` | pH | |
| `ec` | mS/cm | |
| `temperature_c` | °C | Air temperature |
| `humidity` | % RH | |
| `light_intensity` | lux | Sensor not built yet — currently always `null` |
| `co2` | ppm | |

**No chunking is needed.** An earlier draft allowed for splitting rows across notifications;
measured messages are ~120 bytes, so a row always fits in one. If a message ever exceeds the
limit the Pi sends `{"t":"err","msg":"row too large"}` rather than truncating, so oversize is an
error case, not a reassembly problem.

### Correction to the earlier plan

An earlier planning doc said the app's existing mapping would work *"as long as the Pi's SQLite
column names match the Supabase table"*. **They do not match** — the Pi stores one row per
individual reading, not one row per snapshot.

This was fixed **on the Pi**: readings are pivoted into wide snapshots before sending, so the
payload mirrors the Supabase shape. The practical consequence is the one that draft wanted —
the app's existing Supabase row-mapping path works unchanged. Do not re-fix this in the app;
the names already line up.

---

## Phase 1 — Native setup and permissions

BLE does not work in Expo Go or on web. This requires a development build.

```bash
npx expo install react-native-ble-plx expo-dev-client buffer
```

Add the `react-native-ble-plx` config plugin in `app.json` with `isBackgroundEnabled: false`,
`neverForLocation: true`, `modes: []`. From then on build with `npx expo run:android` or
`eas build --profile development`.

Guard every BLE call with `Platform.OS === "android"` and hide or disable the Bluetooth entry
point elsewhere, so the web build and Expo Go keep working.

**Runtime permissions**, requested before scanning:
- Android 12+: `BLUETOOTH_SCAN`, `BLUETOOTH_CONNECT`
- Android 11 and below: `ACCESS_FINE_LOCATION`

Check the adapter state first and prompt if the phone's Bluetooth is off. Denied permissions
must produce a clear message, never a crash.

---

## Phase 2 — A dedicated BLE module

Put the BLE code in its own module rather than in the main screen component, so the transport
is testable and the screen stays readable. It owns a single `BleManager` and the UUID
constants, and exposes two functions.

**`scanForPis(onFound)`** — start a device scan *filtered by the service UUID*, dedupe by
device id, stop after ~8s, return a stop function. Filtering means only our Pis appear rather
than every nearby device.

**`fetchRowsOverBle(deviceId)`** → `{ cols, rows, sensorsOk }`

1. Connect, requesting an MTU of 517.
2. Discover services and characteristics.
3. **Subscribe to DATA before writing.** Not optional — notifications sent before the
   subscription exists are lost, and the symptom is a silent empty transfer.
4. Write `GET 10` to CONTROL, base64-encoded: `Buffer.from("GET 10").toString("base64")`.
5. Decode each notification: `Buffer.from(value, "base64").toString("utf8")`, then `JSON.parse`.
6. Resolve on `{"t":"end"}` once every index `0 .. n-1` has arrived. Reject on `{"t":"err"}`,
   on a 10s timeout, or on a missing index.
7. In `finally`: remove the subscription and cancel the connection.

Handle `n: 0` — a valid, empty response when the Pi has no readings yet.

---

## Phase 3 — The table

Ten rows by seven columns does not fit a phone screen. Recommended shape:

```
┌──────────┬──────┬──────┬────────┬──────┬───────┐
│ Time     │ pH   │ EC   │ Temp   │ RH   │ CO₂   │  ← horizontally scrollable
├──────────┼──────┼──────┼────────┼──────┼───────┤
│ 18:50:48 │ 5.93 │ 1.17 │ 22.0°C │ 61%  │ 822   │
│ 18:50:18 │ 5.79 │ 1.09 │ 22.3°C │ 62%  │ 801   │
└──────────┴──────┴──────┴────────┴──────┴───────┘
```

- **Sticky time column**, the rest horizontally scrollable. Time anchors every row, so it
  should never scroll out of view.
- **Rows arrive newest first.** Display them that way; reverse only when feeding a chart that
  expects chronological order. Trust the `i` field for ordering, not arrival sequence.
- **Render `null` as `—`, never `0`.** `light_intensity` is currently always null because that
  sensor does not exist yet, and a column of zeroes reads as a real measurement of darkness.
  Any column can be null if a sensor fails.
- **Units belong in the header**, not repeated per cell.
- Consider hiding an all-null column rather than showing a dead one.

### Stale data banner

If the header has `"sensors_ok": false`, the Pi is reachable but its newest reading is over
three minutes old — the sensor loop has stalled. Show the data with a clear "may be stale"
marker. Silently presenting stale numbers as live is worse than showing an error.

---

## Phase 4 — Wire into the offline fallback

- When the Supabase fetch fails, set an `offline` flag and surface it in the top bar
  ("Offline: tap ᛒ" or similar).
- Replace the simulated device list and fake `setTimeout` delays in the existing Bluetooth
  modal with the real scan and fetch. Keep its current phases (idle / scanning / connecting)
  and add a `transferring` phase.
- Feed results through the same state path as Supabase data, and label the last-sync indicator
  as "via BLE" so the user knows which source they are seeing.
- The next successful Supabase fetch clears `offline` automatically.

---

## Gotchas already hit during Pi bring-up

These cost real time and will bite the app side too:

1. **Android caches GATT tables.** After the Pi's characteristics changed, the phone kept
   serving a stale, empty service definition. "Refresh Services" in nRF Connect, or toggling
   phone Bluetooth, clears it. Whenever the service definition changes during development,
   assume the phone is lying. This looks exactly like a server bug and is not one.
2. **Subscribe before writing**, or the response goes into the void.
3. **Values are base64 in both directions** — the write payload and every notification.
4. **A second `GET` during a transfer is ignored** by the Pi, so a double tap is harmless but
   will not restart anything. Disable the trigger while `transferring`.

---

## Verification

1. **Baseline, no app code** (on the Pi): seed dummy readings, then `GET 10` from nRF Connect —
   expect 12 messages. Already passing.
2. **Build:** type-check clean; the dev build installs on a *physical* phone. The Android
   emulator has no Bluetooth.
3. **Happy path:** phone Wi-Fi off, wait for the Supabase fetch to fail, confirm the offline
   state, connect over BLE, confirm 10 rows render with values matching what the Pi's database
   holds.
4. **Failure cases:** permissions denied; phone Bluetooth off; the Pi's BLE service stopped
   mid-transfer (expect the 10s timeout, an error, and a return to idle); Wi-Fi restored clears
   offline.
5. **Empty and stale:** against a Pi with no readings (`n: 0`), and one whose sensor loop is
   stopped (`sensors_ok: false`).
6. **Web / Expo Go:** the app still loads and the Bluetooth entry point is hidden or disabled.

---

## Not in scope

Writes, commands and control from the app. This path is read-only by design — the phone cannot
influence dosing or the control loop, which keeps the project spec's "BLE is explicitly not a
control path" property intact even though history was added to it.
