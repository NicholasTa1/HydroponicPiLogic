# Plan: BLE reading in the React Native app

App-side work to read sensor history from the Pi over BLE and show it to the user as a table,
for when Supabase is unreachable.

**The Pi side is done and tested.** It advertises, serves `GET <n>`, and a real transfer has
been verified end to end with nRF Connect on an Android phone. This plan covers only the app.

Read [`ble-protocol.md`](./ble-protocol.md) first — it is the contract, and this plan assumes it
rather than repeating it.

---

## What is already true (verified on hardware, not assumed)

| | |
|---|---|
| Advertised name | `HydroPi-<hostname>`, e.g. `HydroPi-homegrow` |
| Service | `6e3a1f80-5c21-4a7e-9d1b-2f8c4a0e7b31` |
| CONTROL | `...1f81` — properties: WRITE, WRITE NO RESPONSE |
| DATA | `...1f82` — properties: NOTIFY, READ |
| `GET 10` returns | 12 notifications: 1 header + 10 rows + 1 end marker |
| Message size | ~120 bytes, far below the 517-byte MTU |

**No chunking is needed.** The original plan allowed for splitting rows across notifications;
measured messages are ~120 bytes, so one row always fits in one notification. If a message ever
exceeds the limit the Pi sends `{"t":"err","msg":"row too large"}` rather than truncating, so
the app can treat oversize as an error rather than implementing chunk reassembly.

### Correction to the earlier plan

The earlier planning doc said the app's existing mapping would work *"as long as the Pi's SQLite
column names match the Supabase table"*. **They do not match** — the Pi stores one row per
individual reading, not one row per snapshot.

This was fixed **on the Pi**: readings are pivoted into wide snapshots before sending, so the
payload mirrors the Supabase shape. The practical consequence for the app is the one the plan
originally wanted — the existing row-mapping path works unchanged. Do not "fix" this again in
the app; the column names already line up.

---

## Phase 1 — Native setup and permissions

BLE does not work in Expo Go or on web. This requires a development build.

```bash
npx expo install react-native-ble-plx expo-dev-client buffer
```

Add the `react-native-ble-plx` config plugin in `app.json` with `isBackgroundEnabled: false`,
`neverForLocation: true`, `modes: []`. From then on build with `npx expo run:android` or
`eas build --profile development`.

Guard every BLE call with `Platform.OS === "android"` and hide or disable the Bluetooth button
elsewhere, so the web build and Expo Go keep working.

**Runtime permissions**, requested before scanning:
- Android 12+: `BLUETOOTH_SCAN`, `BLUETOOTH_CONNECT`
- Android 11 and below: `ACCESS_FINE_LOCATION`

Check `manager.state()` first and prompt if the phone's Bluetooth is off. Denied permissions
must produce a clear message, never a crash.

---

## Phase 2 — The BLE module (`src/ble/pi-ble.ts`)

Keep this out of the main screen component. Two exported functions:

**`scanForPis(onFound)`** — `startDeviceScan([HYDRO_SERVICE_UUID], ...)`, dedupe by
`device.id`, stop after ~8s, return a stop function. Filtering by service UUID means only our
Pis appear, not every nearby device.

**`fetchRowsOverBle(deviceId)`** → `{ cols, rows, sensorsOk }`

1. `connectToDevice(id, { requestMTU: 517 })`
2. `discoverAllServicesAndCharacteristics()`
3. **Subscribe to DATA before writing.** `monitorCharacteristicForService(...)`. This ordering
   is not optional — notifications sent before the subscription exists are simply lost.
4. Write `GET 10` to CONTROL, base64-encoded: `Buffer.from("GET 10").toString("base64")`
5. Each notification value arrives base64: decode with
   `Buffer.from(v, "base64").toString("utf8")`, then `JSON.parse`.
6. Resolve on `{"t":"end"}` once every index `0..n-1` has arrived. Reject on `{"t":"err"}`, on
   a 10s timeout, or on a missing index.
7. `finally`: remove the subscription and `cancelDeviceConnection`.

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

- **Sticky time column**, the rest horizontally scrollable. Time is the anchor for reading any
  row, so it should never scroll out of view.
- **Rows arrive newest first.** Display them that way (most recent at top is what a user
  wants); reverse only if feeding a chart that expects chronological order. The `i` field is
  the authority on ordering, not arrival sequence.
- **Render `null` as `—`, never `0`.** `light_intensity` is currently always null because that
  sensor does not exist yet, and a column of zeroes would read as a real measurement of
  darkness. Any column can be null if a sensor fails.
- **Units belong in the header**, not repeated in every cell.
- Consider hiding all-null columns entirely rather than showing a dead column.

### Stale data banner

If the header has `"sensors_ok": false`, the Pi is reachable but its newest reading is over
three minutes old — the sensor loop has stalled. Show the data with a clear "readings may be
stale" marker rather than presenting it as current. Silently showing stale numbers as live is
worse than showing an error.

---

## Phase 4 — Wire into the offline fallback

- When the Supabase fetch fails, set an `offline` flag and show "Offline: tap ᛒ" in the top bar.
- Replace `DUMMY_BT_DEVICES` and the simulated `setTimeout` calls in `BluetoothModal` with the
  real `scanForPis` / `fetchRowsOverBle`. Keep the existing `idle` / `scanning` / `connecting`
  phases and add `transferring`.
- Feed results through the same state path as Supabase data, labelling `lastSync` as "via BLE"
  so the user knows which source they are looking at.
- The next successful Supabase fetch clears `offline` automatically.

*(Component and prop names here come from the earlier planning doc, not from reading the app
source — adjust to whatever is actually there.)*

---

## Gotchas already hit on the Pi side

These cost real time during Pi bring-up and will bite the app side too:

1. **Android caches GATT tables.** After the Pi's characteristics changed, the phone kept
   showing a stale, empty service. "Refresh Services" in nRF, or toggling phone Bluetooth,
   fixes it. During development, whenever the service definition changes, assume the phone is
   lying until you clear the cache. This will look like a server bug and will not be one.
2. **Subscribe before writing**, or the response is sent into the void.
3. **Values are base64 in both directions** in `react-native-ble-plx` — the write payload and
   every notification.
4. **A second `GET` during a transfer is ignored** by the Pi, so a double tap is harmless but
   will not restart anything. Disable the button while `transferring`.

---

## Verification

1. **Baseline, no app code:** `python3 seed_dummy_data.py` on the Pi, then `GET 10` from nRF
   Connect — 12 messages. Already passing.
2. **Build:** `npx tsc --noEmit` clean; `npx expo run:android` installs on a physical phone.
   The emulator has no Bluetooth.
3. **Happy path:** phone Wi-Fi off, wait for the Supabase fetch to fail, confirm the offline
   state, tap ᛒ, pick the Pi, confirm 10 rows render with values matching
   `sqlite3 hydro.db "SELECT * FROM readings ORDER BY id DESC LIMIT 20;"`.
4. **Failure cases:** permissions denied; phone Bluetooth off; `hydro-ble` stopped mid-transfer
   (expect the 10s timeout, an error, and a return to idle); Wi-Fi restored clears offline.
5. **Empty and stale:** test against a Pi with no readings (`n: 0`) and one whose sensor loop is
   stopped (`sensors_ok: false`).
6. **Web / Expo Go:** app still loads and the ᛒ button is hidden or disabled.

---

## Not in scope

Writes, commands and control from the app. This path is read-only by design — the phone cannot
influence dosing or the control loop, which keeps spec §9's "BLE is explicitly not a control
path" intact even though history was added to it.
