# Progress Log

Running log of work on this repo. Newest entries at the bottom. Every session updates this file
as part of its commit, not as an afterthought — it's the fastest way to reconstruct project state
without re-reading the whole diff history.

Entry format:

```
## YYYY-MM-DD
- What changed and why (not just "what files changed" — the reasoning/decision behind it)
- Anything left half-done or intentionally deferred
```

---

## Reference: hardware wiring

Everything analog goes through one Adafruit ADS1115 ADC on I2C, because the Pi has no analog
inputs of its own.

**ADS1115 -> Pi**

| ADS1115 | Pi pin | Note |
|---|---|---|
| VIN | 3.3V (pin 1) | **Not 5V** — see warning below |
| GND | GND (pin 6) | |
| SCL | GPIO3 / SCL (pin 5) | |
| SDA | GPIO2 / SDA (pin 3) | |

**DFRobot pH board -> ADS1115**: `V+` to Pi 5V (pin 2), `GND` to Pi GND, analog out to **A0**,
ideally through a 10K series resistor. The board wants a full 5.00V for accuracy.

**SenseCAP S-EC-01 (analog mode) -> ADS1115**: Red `V+` to Pi 5V, Black `GND` to Pi GND,
Blue `O1` to **A1**. No series resistor needed — its output maxes at 2V.

**Adafruit SCD-41 (PID 5190) -> Pi** — CO2, air temp, humidity. I2C, not through the ADC.
STEMMA QT to Pi 3.3V, GND, SDA, SCL. Appears at **0x62**.

**Adafruit VEML7700 -> Pi** — light. I2C. STEMMA QT to Pi 3.3V, GND, SDA, SCL. Appears at
**0x10**. Has its own regulator, level shifting and I2C pullups, so 3.3V or 5V are both safe.

**DS18B20 (Adafruit 381) -> Pi** — water temperature. 1-Wire, not I2C. Red to **3.3V**, Black
or Blue to GND, White or Yellow to **GPIO 4 (pin 7)**. Requires the supplied **4.7k pullup**
between data and VCC, and 1-Wire enabled: `sudo raspi-config nonint do_onewire 0` + reboot.
Appears as `/sys/bus/w1/devices/28-*`, not in `i2cdetect`. No divider needed (3.0-5.5V part).

**DFRobot SEN0204 water level -> Pi** — GPIO, not I2C. Brown `VCC` to **5V**, Blue `GND` to Pi
GND, Yellow `OUT` through a **divider** to **GPIO 17 (pin 11)**.

> **The divider is mandatory.** This sensor's output swings to its supply, and it needs 5V
> minimum, so OUT sits at 5V and will damage a Pi GPIO. 10k from OUT to the GPIO plus 20k from
> that GPIO to GND gives ~3.3V. There is no "power it lower" option here, unlike the ADS1115:
> 3.3V is below the sensor's minimum supply.

**Why VIN must be 3.3V, not 5V:** the ADS1115 breakout's SDA/SCL pullups go to VIN. At 5V they
back-feed the Pi's GPIO, which is not 5V tolerant. The tradeoff is that the ADC's absolute max
analog input becomes 3.6V (VDD + 0.3V), which the 5V-powered pH board can exceed under a fault
— hence the series resistor. The EC sensor is unaffected either way at 0-2V.

Expected I2C addresses (`i2cdetect -y 1`): **0x48** ADS1115, **0x62** SCD-41,
**0x10** VEML7700. The water level and DS18B20 sensors are not on I2C and will never appear.

**If the scan goes completely empty, suspect the device you just added.** One miswired board
pulls SDA or SCL low and every device disappears at once, which looks like total failure
rather than one bad part. Unplug the newest thing and rescan. Swapped SDA/SCL is the usual
cause.

## Reference: hardware status

What has actually been verified against real hardware, as distinct from written and
unit-tested. Keep this current — "the code exists" and "the sensor works" are different
claims, and the dated entries below cannot be read at a glance.

| Sensor | Part | Status as of 2026-10-16 |
|---|---|---|
| ADC | ADS1115 | **Tabled, unresolved** — see 2026-10-26. Power supply is the current suspicion |
| pH | DFRobot SEN0161/9 | **Blocked** — read correctly once, now blocked on the ADC |
| Light | VEML7700 | **Working** — initial failure was wiring |
| EC | SenseCAP S-EC-01 | **Not yet tested** — cable has no exposed conductors to connect to |
| Water level | DFRobot SEN0204 | **Not yet tested** — blocked on building the divider |
| Water temp | DS18B20 | **Working** — needed 1-Wire enabling via raspi-config + reboot |
| CO2 / air temp / humidity | SCD41 | **Blocked** — first unit dead on arrival, awaiting replacement |
| BLE transfer | — | **Working** — verified end to end with nRF Connect |

Note the distinction between **not working** and **not yet tested**. EC, water level and
water temp have never produced a reading at all — all three are blocked on physical wiring,
not on software faults. Nobody should go looking for bugs in their drivers until each has
been connected and produced at least one value.

pH and EC both depend on the ADS1115, so while that is damaged neither can be tested.

## Reference: running on the Pi

```bash
cd ~/HydroponicPiLogic/pi
source .venv/bin/activate          # create once: python3 -m venv .venv
pip install -r requirements.txt    # supabase, python-dotenv, smbus2, gpiozero, bless

i2cdetect -y 1                     # expect 48, 62, 10 for whatever is wired
ls /sys/bus/w1/devices/            # expect a 28-* entry for the DS18B20

python3 read_adc.py                # live ADC voltages (pH/EC), Ctrl-C to stop
python3 read_sensors.py            # every sensor, converted values -- the main bring-up tool
python3 calibrate_ph.py            # needs pH 4.00 + 9.18 buffer solutions
python3 test_ph_sync.py            # one reading end to end into Supabase
python3 seed_dummy_data.py         # 10 fake cycles, for testing BLE without sensors
python3 ble_server.py              # BLE peripheral; pair with nRF Connect
python3 main.py                    # the real 30s sample / 5min sync loop
```

One-time setup, each needing a reboot: `sudo raspi-config nonint do_i2c 0` (I2C) and
`sudo raspi-config nonint do_onewire 0` (1-Wire, for the DS18B20).

Run these from inside `pi/` — `DB_PATH` is relative, so `hydro.db` lands in the working
directory. Neither `.env` (credentials) nor `.venv` (packages) comes down with a `git clone`;
both are gitignored and must be recreated per machine.

---

## 2026-09-20
- Added `PI_CONTROL_SPEC.md`: handoff spec for the Pi-side control subsystem (sensing, dosing,
  safety, local storage, Supabase sync, BLE). Full rationale lives in that file.
- Added `pi/` skeleton: config, sensor interfaces (master-basin EC/pH/water-level; per-basin
  temperature/water-temp/humidity/CO2/light), SQLite 5-minute buffer, sync stub, fan
  hysteresis feedback loop (on >72F, off <58F), and the orchestration loop in `main.py`.
- All sensor `read()` methods are stubs (`NotImplementedError`) — no hardware wired up yet.
- Note: this skeleton clears the local SQLite buffer every 5 minutes after a successful sync,
  which differs from the full-crop-cycle retention originally described in
  `PI_CONTROL_SPEC.md` section 7. Flagged, not yet reconciled.
- Basin count is a placeholder (`BASIN_IDS = ["basin_1"]` in `pi/config.py`) — update once the
  real basin count is known.
- Next: wire real drivers into the sensor stubs, starting with EZO-EC/pH over I2C.

## 2026-09-27
- Wired the first end-to-end pipeline: dummy pH reading -> local SQLite buffer -> remote
  Supabase table, confirmed working with real inserts landing in the project.
- `PHSensor.read()` now returns dummy data (`random.uniform(5.5, 6.5)`) instead of raising
  `NotImplementedError`, standing in for the real EZO-pH I2C read until that hardware is on
  the bench. Other sensors (EC, water level, per-basin env sensors) are still stubs.
- `sync.py` now does a real Supabase insert via `supabase-py`, using credentials from a local
  `.env` (never committed — see `pi/.env.example`, and `.gitignore` at repo root).
- Discovered the Supabase project already had a `sensor_readings` table (from earlier/other
  work), with a *wide* schema (`id, humidity, temperature_c, light_intensity, ec, ph,
  recorded_at`) and no `basin_id` column — different from the long/narrow format our local
  SQLite `readings` table uses. Went with the existing table rather than creating a
  duplicate; `sync.py`'s `_row_to_record` only maps the `ph` column for now and raises on any
  other sensor. `pi/supabase_schema.sql` documents this rather than creating a table.
  Open item: this wide table has no room for multiple basins — will need a `basin_id` column
  or a schema rethink once more than one basin/sensor needs to sync. Not decided unilaterally
  since the app/CV side may already depend on the current shape.
- Row Level Security on `sensor_readings` initially blocked inserts from the publishable key
  (expected/correct behavior). Resolved by granting the key insert access from the Supabase
  side rather than switching to the service_role key.
- Added `pi/test_ph_sync.py`: manual one-shot smoke test for this pipeline (read -> insert ->
  sync -> clear) without waiting on the 30s/5min loop in `main.py`.
- Added `.gitignore` (repo root) and `pi/.env.example` so Supabase credentials and the local
  `hydro.db` file never get committed.

## 2026-09-28
- Hardware for pH turned out to be different from what `PI_CONTROL_SPEC.md` assumed: it is a
  **DFRobot analog pH board (SEN0161/SEN0169)** read through an **Adafruit ADS1115 I2C ADC**,
  not an Atlas Scientific EZO board on I2C. The Pi has no analog inputs, hence the ADC.
- `PHSensor` now does a real read instead of returning dummy data: median of 5 ADS1115 samples
  on channel A0, converted `pH = PH_SLOPE * volts + PH_INTERCEPT`. Working in volts (not raw
  ADC counts) keeps the conversion independent of ADC resolution, which is what DFRobot's FAQ
  warns about for non-Arduino controllers.
- Added `pi/sensors/ads1115.py`, a minimal register-level ADS1115 driver over `smbus2`.
  Deliberately NOT using the Adafruit CircuitPython library: the official guide shows two
  different library APIs on adjacent pages (a restructure), and Blinka adds platform-detection
  problems on Pi 5. The register map is fixed in silicon, so this can't drift. Verified the
  config word computes to 0xC383 (known-good for A0 at gain 1) and the two's-complement ->
  volts math is right.
- The ADC is constructed lazily on first read so `build_sensors()` stays side-effect free and
  still works off the Pi (where `smbus2` does not exist); a missing bus is then caught by the
  existing per-sensor handler in `read_all` rather than crashing startup.
- Added `pi/calibrate_ph.py` for the two-point buffer calibration (pH 4.00 + 9.18/10.00). Until
  it is run, `PH_SLOPE`/`PH_INTERCEPT` are DFRobot's uncalibrated defaults (3.5 / 0.0) and
  readings will look plausible but be WRONG — do not treat them as a hardware verdict.
  Note: DFRobot's own sample sketch computes the intercept against the previous slope, which is
  a bug; `calibrate_ph.py` uses the newly derived slope.
- Removed `EZO_PH_ADDRESS` (superseded). `EZO_EC_ADDRESS` left in place but flagged — EC
  hardware is not confirmed and may also end up analog on a spare ADC channel.

Open hardware concerns found in the vendor docs, not yet resolved:
- **Voltage**: ADS1115 absolute max analog input is VDD + 0.3V. The pH board is a 5V module and
  can swing to 5V; with the ADC on the Pi's 3.3V that is over the limit. Normal pH 4-10 output
  is ~1.1-2.9V so routine operation is fine, but a faulty/disconnected probe is not. A 10K
  series resistor into A0 is cheap insurance. Do NOT power the ADS1115 at 5V to work around
  this — its SDA/SCL pullups go to VIN and would back-feed the Pi's non-5V-tolerant GPIO.
- **EC/pH interference**: DFRobot FAQ Q2 says an EC meter (or any powered device, incl. a pump)
  in the same container corrupts pH readings, and these analog boards have no isolation. This
  conflicts with spec §5, which has EC and pH both in the master basin with circulation running.
  Needs a real fix (sequencing reads, isolation, or separate containers).
- **Probe choice**: SEN0161 cannot be continuously immersed (~6 months, bulb only). SEN0169 is
  fully waterproof, ~2 years. Spec has probes submerged for a full crop cycle, so SEN0169 is the
  correct part — confirm which one we actually have.
- Spec §6 wants raw millivolts logged alongside pH for drift analysis. Not done: needs a schema
  change locally and remotely. Worth doing before the real crop cycle starts.

## 2026-10-01
- Pi environment is now working. Two snags worth recording, both environment rather than code:
  - The venv had never actually been created on the Pi. Note that `.env` (Supabase credentials)
    and `.venv` (Python environment) are easy to confuse — both are gitignored, so neither
    arrives with a `git clone` and both must be recreated per machine.
  - `i2cdetect -y 1` failed with "could not open file `/dev/i2c-1`". Cause was simply that the
    I2C interface had never been enabled; `sudo raspi-config nonint do_i2c 0` plus a reboot
    fixed it (the `0` means enable — raspi-config's nonint flags read backwards).
- `i2cdetect -y 1` now returns a normal empty grid, which is correct with nothing wired up. The
  I2C bus is confirmed working end to end on the Pi.

- EC sensor implemented: **SenseCAP S-EC-01 in analog mode**, 0-2V output on ADS1115 channel A1,
  sharing the same ADC as pH. Reported in mS/cm to match spec §5 setpoints and the remote `ec`
  column, though the datasheet works in uS/cm.
- Both analog sensors now share one `ADS1115` handle via `get_shared_adc()` instead of each
  opening its own SMBus connection to the same chip. Removed the per-sensor `close()` methods,
  which would have been wrong against a shared handle (nothing called them).
- `sync.py` now maps EC as well as pH, via a `_REMOTE_COLUMNS` dict. Unmapped sensors still
  raise rather than silently dropping.
- Added `pi/read_adc.py`: live voltage readout per channel alongside the converted value, to
  separate "probe not wired up" from "conversion constants wrong" during bring-up.
- **Good news on an open concern:** the S-EC-01 datasheet specifies an *isolated sensor input*,
  which is the exact mitigation for the EC-corrupts-pH problem flagged on 2026-09-28. That
  specific mechanism should be handled. Not a complete all-clear — the DFRobot warning also
  covers any powered device in the tank including the circulation pump, and the pH board itself
  is unisolated — so still verify empirically with the pump running before trusting it.
- Two EC things that still need confirming against the physical unit:
  - **Output range variant.** `EC_VOLTS_TO_US_CM` currently assumes the 0-2000 uS/cm unit
    (multiplier 1000). The datasheet offers 1000/2500/5000/10000 depending on what was ordered,
    so a wrong value scales every reading by up to 10x. Identify it by reading the voltage in
    1413 uS/cm solution: 1.413V / 0.565V / 0.283V / 0.141V respectively. Worth noting the
    0-2000 variant is by far the best fit for lettuce (0.8-1.3 mS/cm sits mid-scale); on the
    0-20000 variant the whole crop range is squeezed into the bottom ~7% of the output.
  - **Power draw.** The sensor takes 3.9-30V and is specced at 40mA idle / 80mA max *at 24V*.
    Run from the Pi's 5V rail that is roughly 200-400mA, which is a real load on top of the pH
    board and the Pi itself. A separate supply is an option since it accepts up to 30V — but
    its GND must still tie to Pi GND, as the analog output is referenced to it.
- EC calibration is on-device (buttons SW2/SW3 against 1413 and 12880 uS/cm solutions), not a
  slope we fit, so there is deliberately no EC equivalent of `calibrate_ph.py`. Temperature
  compensation is also internal to the sensor (2%/degC default), which satisfies spec §4
  without software work.

## 2026-10-03
- **First hardware confirmation:** `i2cdetect -y 1` sees the ADS1115 at 0x48 on the real Pi.
  pH bring-up in progress; still uncalibrated at that point.
- Air temperature / humidity / CO2 implemented against the **Sensirion SCD41** (Adafruit PID
  5190). Worth noting the part is an SCD**41**, not the SCD40 the breakout is often assumed to
  be — confirmed from the DigiKey listing before writing anything.
- Added `pi/sensors/scd4x.py`, a register-level driver over `smbus2`, consistent with the
  ADS1115 decision to avoid CircuitPython/Blinka. Verified against the datasheet's own worked
  example (v1.7 Table 11): all three CRC test vectors match, and the response
  `01f4 33 / 6667 a2 / 5eb9 3c` decodes to exactly 500 ppm, 25.00 C, 37.00 %. A corrupted CRC
  is rejected rather than believed.
- One chip supplies all three values, so a single read is cached for one 5-second measurement
  interval and served to all three Sensor classes. That is correctness, not optimisation: the
  three readings must come from the same sample, and the chip only produces one every 5s.
- `start()` issues stop_periodic_measurement first and waits the datasheet's 500ms. Without it,
  a sensor left in periodic mode by a previous run rejects the start command, which looks
  exactly like a wiring fault on every restart.
- **Unit change:** air temperature is now Celsius (was declared "F"). The SCD41 reports Celsius
  and the remote column is literally named `temperature_c`, so Celsius is stored. The fan
  thresholds stay Fahrenheit as specified (72/58) and `FanController.update` converts. Verified
  the hysteresis latches on above 72F and holds until below 58F. `water_temp` relabelled to C
  for consistency; still a stub.
- **Fixed a latent crash this would have triggered:** `sync._row_to_record` raised on unmapped
  sensors, and that exception escaped `send_batch` (whose try only wrapped the insert) and was
  uncaught in `main.sync_and_clear`. Harmless while only pH existed; once CO2 readings started
  being generated it would have taken down the sync loop *and every other reading in the batch*
  on the first cycle. Unmapped sensors are now skipped with a warning.
- Mapped `temperature`->`temperature_c`, `humidity`->`humidity`, `light`->`light_intensity`.
- **CO2 now syncs.** A `co2` column was added to `sensor_readings` and mapped in
  `_REMOTE_COLUMNS`; verified with a real insert landing as row id 12.
- **The wide-table mismatch is now visibly a problem.** Three readings taken in the same cycle
  land as three separate rows, each with one populated column and the rest null (rows 12/13/14),
  versus the original seed rows which carry every value together. Invisible when only pH
  existed; with five sensors any consumer has to stitch rows back together by timestamp. Two
  ways out, and it needs a decision with whoever owns the app side:
    1. Group a cycle's readings into one row before sending (keeps the current table shape).
    2. Move the remote table to the same long format as local SQLite
       (`ts, basin_id, sensor, value, unit`), which also solves the missing `basin_id` and
       would stop needing a new column per sensor.
  Option 2 matches where the multi-basin design is heading; option 1 is less disruptive to
  anything already reading the table.
- **Multi-basin blocker:** the SCD41's I2C address 0x62 is fixed in silicon and cannot be
  changed, so two of them cannot share a bus. Per-basin air temp/humidity/CO2 will need an I2C
  multiplexer (e.g. TCA9548A). Not urgent at `BASIN_IDS = ["basin_1"]`, but it constrains the
  multi-basin design in spec §5 and should be priced in before ordering more sensors.

## 2026-10-05
- **The first SCD41 was dead on arrival.** It never appeared at 0x62 under any condition.
  Ruled out, in order: I2C not enabled (bus was already proven working), the pH probe being
  unwired (irrelevant — the ADS1115 enumerates on its own power and SDA/SCL, independent of
  anything attached to its analog inputs), 3.3V rail droop (moved to 5V, which the breakout
  supports at VIN with its own regulator and level shifting), and missing common ground with
  the external 5V supply. None of it was the cause; the part itself is faulty.
- Nothing in the code needs to change for the replacement. `sensors/scd4x.py` was verified
  against the datasheet's worked example, not against this unit, so it was never implicated.
  On arrival: `i2cdetect -y 1` should show `62`, then `read_sensors.py`, then breathe on it and
  watch CO2 climb past 1500 ppm.
- Worth doing before wiring a replacement into anything permanent: confirm it enumerates while
  it is still easy to swap.

- **Local retention reversed to the spec's design.** Readings are no longer deleted after sync;
  rows carry a `synced` flag and are marked rather than removed. This resolves the conflict
  flagged on 2026-09-20 between the 5-minute-buffer instruction and spec §7/§8, in favour of
  the spec. Driven by two things: the capstone deliverable is the analysis, and deleted raw
  data is unrecoverable with only one crop cycle before the deadline; and once Supabase
  downsamples older data per spec §8, the Pi becomes the only full-resolution copy.
  Storage is a non-issue — ~800k rows / under 100MB for a whole cycle.
- `sync_and_clear` -> `sync_pending`, which drains the queue in batches of `SYNC_BATCH_LIMIT`
  (300) oldest-first, per spec §8.
- **Subtle trap avoided:** readings with no remote column (currently water_temp, and light once
  implemented) are marked synced along with the rest of a successful batch. Leaving them
  unsynced would park them permanently at the front of the oldest-first queue, and once enough
  accumulated they would fill every batch and starve real readings forever. Verified with a
  test that puts unmappable rows at the front of the queue with a small batch limit.
  Consequence: if a column is added later, backfilling history is a deliberate one-off (reset
  `synced` for that sensor), not something the loop does on its own.
- Partial index `(ts) WHERE synced = 0` so the sync queue stays a small index regardless of
  table size. A plain scan stays fast for the first week and then quietly stops being fast.
- WAL mode enabled, so a second process (BLE) can read while the control loop writes instead of
  hitting intermittent "database is locked".
- `connect()` migrates an existing database in place by adding the `synced` column, verified
  against a database built in the old schema — the Pi's existing `hydro.db` needs no action.
- `clear_readings()` removed; `get_recent_readings()` added for the BLE read path.
- One behaviour change worth knowing: deleting-after-sync made duplicate sends structurally
  impossible. With a flag, a power cut between a successful insert and the flag update would
  re-send those rows next cycle. Benign (identical values and timestamps) and rare, but it is
  no longer impossible. A unique constraint on the remote side would close it if it matters.

- **BLE Part 1 (Pi side) implemented.** Separate process, read-only, history-only.
- **Corrected a false assumption in the plan doc.** Part 2d assumed "the Pi's SQLite column
  names (`recorded_at`, `ph`, `temperature_c`, ...) match the Supabase table". They do not —
  those are the *Supabase* columns; local SQLite is long-format (`ts, basin_id, sensor, value`),
  one row per individual reading. "The latest 10 rows" locally means ten single sensor values,
  roughly two sampling cycles, not ten snapshots. Resolved on the Pi: readings are pivoted into
  wide snapshots before sending, so the app's existing row-mapping path works unchanged and the
  BLE payload mirrors Supabase. No app-side change needed versus what the plan already assumed.
- `REMOTE_COLUMNS` moved from `sync.py` to `config.py` so sync and BLE share one mapping and
  cannot drift into reporting the same reading under different names. It also keeps the BLE
  process from importing the Supabase client.
- **Found and fixed a latent performance bug from 2026-10-05.** The partial index
  `(ts) WHERE synced = 0` cannot serve "newest N readings" — it excludes synced rows, which is
  nearly the whole table — so `get_recent_readings` would full-scan and sort ~800k rows. Added
  a plain `readings_ts_idx ON readings (ts)`.
- Added `busy_timeout` (2s) and `db.connect_readonly()` for other processes.
- Split the BLE work in two so the risky part is testable without a radio:
  `ble_protocol.py` is pure (pivot, framing, request parsing) and verified against three
  synthetic sampling cycles; `ble_server.py` is the `bless`/BlueZ transport.
- Protocol details: one message per cycle newest-first, fixed column order read positionally,
  `sensors_ok` false when the newest reading is >3min old (Pi reachable but loop stalled),
  oversize messages reported as an error rather than silently truncated by the MTU, and a
  second `GET` during a transfer ignored. Cycle grouping is by time proximity rather than
  rounding to a fixed interval, which stays correct when a cycle straddles a boundary or the
  loop runs late.
- Added `docs/ble-protocol.md` (the Part 3 contract, for the app side) and systemd units in
  `pi/systemd/`. Both units set `WorkingDirectory` — without it the relative `DB_PATH` would
  make each service create its own empty `hydro.db` rather than using the real one.
- **Fixed on first real run:** `bless` requires both `read_request_func` and
  `write_request_func`; only the write one was set, so anything reading a characteristic hit
  "read callback is undefined". Reads now return the characteristic's last value — history is
  delivered by notification, so the read path exists to satisfy bless rather than to serve
  data. Also switched the control-write handler from `asyncio.create_task` to
  `run_coroutine_threadsafe`, since that callback is not guaranteed to run on the loop thread
  and `create_task` would fail there with no running loop.
- BlueZ setup notes from the same session: `bluetoothctl power on` failing is usually an rfkill
  soft block (`sudo rfkill unblock bluetooth`), and "failed to register advertisement" after a
  crashed run is usually a stale advertisement holding BlueZ's slot, cleared by
  `sudo systemctl restart bluetooth`.
- Added `pi/seed_dummy_data.py`: 10 cycles of plausible readings so the BLE transfer can be
  tested while the SCD41 is dead and pH/EC are uncalibrated. Rows are inserted with
  `basin_id = 'dummy'` and marked synced immediately, so BLE can see them (it ignores sync
  state) but they never upload and cannot pollute the real dataset. Deliberately a separate
  script rather than dummy values inside `ble_server.py`, which would risk shipping and would
  mask real readings. Remove with
  `sqlite3 hydro.db "DELETE FROM readings WHERE basin_id = 'dummy';"`.
- nRF Connect note: after the earlier crashed runs, Android cached an empty GATT table and
  showed the service with no characteristics. Fixed by Refresh Services / toggling phone
  Bluetooth, not by any server change.
- **BLE Part 1 verified end to end on hardware.** nRF Connect connects to `HydroPi-homegrow`,
  `GET 10` returns 12 notifications (header + 10 rows + end), messages ~120 bytes so no
  chunking is needed. The plan's Part 1 item 5 gate is passed; app work can start.
- Added `docs/ble-app-plan.md` — the Part 2 plan for the app side, written against what was
  actually observed rather than assumed, including the Android GATT-cache trap that cost time
  during bring-up. Next step is Part 1 item 5 — nRF Connect on the
  phone, write `GET 10`, confirm 12 messages arrive — before any app code is written.

## 2026-10-12
- Implemented the **DFRobot SEN0204 / XKC-Y25-T12V** on a GPIO input. Note it was handed over as
  "the water temp sensor" but the datasheet is a non-contact **liquid level** detector, so it
  fills the `WaterLevelSensor` stub. `water_temp` (spec wants a DS18B20) is still unimplemented.
- **WIRING HAZARD — needs a divider or level shifter.** This sensor's output swings to its
  supply voltage and it requires 5V minimum, so OUT sits at 5V. The Pi's GPIO is not 5V
  tolerant and will be damaged by connecting it directly. Use a divider (10k from OUT to the
  GPIO, 20k from GPIO to GND gives ~3.3V) or a level shifter. Unlike the ADS1115 case there is
  no "just power it lower" option, because 3.3V is below the sensor's minimum supply.
- **It is a point detector, not a gauge.** HIGH means liquid is present at the height it is
  mounted at; LOW means it is not. It cannot produce a percentage. Reported as `bool` 1/0
  rather than dressed up as 0%/100%, because spec §5 treats level as a continuous constraint
  ("check projected post-dose level before actuating", "refill below 70%, never exceed 85%")
  and feeding that logic a fake percentage would be worse than reporting the truth. One unit
  gives a single threshold; more units at different heights give more bands. The spec's open
  item (load cell vs ultrasonic) is still open if a real percentage is needed — a load cell
  would also give the cleaner transpiration signal §11 wanted.
- Switched `RPi.GPIO` to `gpiozero` in requirements. RPi.GPIO installs on a Pi 5 but fails at
  runtime; gpiozero works on both Pi 4 and 5 and will serve the relay outputs too.
- Water level has no remote column, so like `water_temp` it is logged locally and dropped at
  sync with a warning rather than silently.

- **DS18B20 water temperature** (Adafruit 381) implemented via the kernel's 1-Wire sysfs
  interface rather than a library — Linux already drives the bus, so there is nothing to break
  on a kernel update and it behaves the same on Pi 4 and 5. Needs 1-Wire enabled
  (`sudo raspi-config nonint do_onewire 0` + reboot) and the supplied 4.7k pullup. It runs at
  3.0-5.5V, so at 3.3V the data line is already Pi-safe — no divider, unlike the level sensor.
  Each probe has a unique factory id and several can share one pin, which is how multiple
  basins will work; `WATER_TEMP_DEVICE_IDS` maps basin to probe, empty meaning auto-detect a
  single probe. Reads are refused rather than reported on CRC failure, on a missing field, and
  on exactly 85.0 C — the power-on reset value, which means a lost conversion or missing
  pullup, not a real temperature.
- **VEML7700 light sensor** implemented at register level (I2C 0x10, fixed). Verified the
  lux-per-count maths against all 24 gain/integration combinations in the datasheet's range
  table — every one matches. Note this part is little-endian, unlike the big-endian SCD4x.
- **Caught a dangerous trap in the lux correction.** Vishay's 4th-order non-linearity
  correction is widely applied unconditionally, but it is only *characterised* at gain 1/8
  with 100ms integration for raw counts above 100. Applied outside that it extrapolates badly:
  at 20k lux it returns +269%, which is divergence presented as a precise number. It is now
  applied only at that operating point, and a raw count above 10000 there is refused with
  instructions to reduce the integration time rather than reported. Darkness still reads 0
  without error, since lights-off is legitimate data.
- Light maps to the existing `light_intensity` column, so it syncs with no schema change.
- **`water_temp` is now the only sensor with no remote column.** It is logged locally and
  dropped at sync. To fix: `alter table sensor_readings add column if not exists water_temp_c
  double precision;` then add `"water_temp": "water_temp_c"` to `REMOTE_COLUMNS` in config.py.
- All eight sensors now have real implementations; no `NotImplementedError` stubs remain.

- **`water_temp` column added remotely but with the wrong type.** It was created as an ARRAY,
  not a number: inserting `19.4` fails with "expected JSON array", while `[19.4]` succeeds.
  Confirmed by testing both rather than inferring from the error. Fix in the SQL editor:
  `alter table sensor_readings drop column water_temp;`
  `alter table sensor_readings add column water_temp double precision;`
  Then uncomment the `water_temp` line in `REMOTE_COLUMNS` in config.py.
- **Resolved 2026-10-19:** the column was rebuilt as `double precision` and the mapping
  re-enabled; a mixed pH / light / water_temp batch was verified landing in Supabase. All
  three working sensors now sync.
- (Below is why the mapping was held back in the meantime.) The mapping was left commented out. **This matters more than it
  looks:** `send_batch` inserts a batch as one request, so a single unacceptable row fails the
  whole batch, `sync_pending` returns without marking anything synced, and the same batch
  retries forever. Enabling the mapping against an array column would therefore have stopped
  *all* syncing, not just water temperature.
- Worth fixing regardless: one malformed reading can currently block the entire sync queue
  indefinitely. Falling back to per-row inserts on a batch failure, or quarantining a row that
  fails repeatedly, would stop one bad value taking everything else down.
- Test rows now in `sensor_readings` needing cleanup from the SQL editor (the Pi's key has
  insert but not delete, so this cannot be done from here):
  `delete from sensor_readings where id in (12, 13, 14, 15, 16);`

## 2026-10-26
- **The ADS1115's analog front end appears to be damaged, and the digital side is fine.**
  Symptoms: `i2cdetect` sees 0x48, the config register reads back exactly what is written, but
  all four channels report multi-volt spreads — including A0 jumpered directly to a shared
  ground rail. A chip that stores configuration correctly but cannot convert any input is a
  damaged analog section, not a wiring fault.
- **How it most likely happened, because this is repeatable and worth avoiding:** VIN came
  loose at some point (the giveaway was the power LED flickering only while `i2cdetect` ran —
  the chip was being back-powered through the SDA/SCL protection diodes, so VDD was
  effectively 0). Meanwhile the 5V-powered pH board kept driving ~2V into A0. The datasheet's
  absolute maximum analog input is **VDD + 0.3V**, so 2V into an unpowered part is far past the
  damage threshold. The digital side recovered when VIN was fixed; the analog inputs did not.
- **Rule for the replacement, and for every analog sensor after it:** bring the ADC up first
  and confirm `i2cdetect` shows 0x48 with a steady power LED, and only then connect a powered
  sensor's output to a channel. Never let a powered sensor drive an input on an ADC that is not
  itself powered.
- Added `pi/diagnose_adc.py`, which is what made this diagnosable: it checks config register
  readback separately from conversions. Voltage readings alone cannot distinguish a damaged
  chip from a floating input, which is why this took several rounds to pin down.
- **Later evidence argues against the damage theory, and this is unresolved.** With nothing
  connected, A0/A1 sit at a stable ~0.5V; connecting anything to *either* makes *both* swing.
  A dead analog front end would be garbage regardless, so the chip is converting. Floating
  being stable while connected is noisy is backwards from normal, and points at the ADC's own
  ground/supply reference moving rather than the chip being dead. Readings are single-ended
  (MUX 0x4-0x7, AINx vs GND), so the ground reference *is* the measurement reference — a bad
  one makes readings meaningless rather than merely noisy, which is why this looked like chip
  damage. Current suspicion is the Pi's power supply; `vcgencmd get_throttled` and measuring
  VIN under load are the unfinished checks. Differential mode (A0 vs A1) would sidestep the
  ground reference entirely and is worth trying as a diagnostic.
- Wrong turns worth recording so they are not repeated: the A+/A- pins at the ends of the
  channel header are outputs, not inputs, and the channel order runs A+ A3 A2 A1 A0 A- — but
  that was not the problem here, the jumper was on A0 throughout. Breadboard power rails split
  in the middle on many boards, also not the cause. Both are still worth checking first on any
  similar fault, since they cost nothing to rule out.

**Stopped here (2026-10-01):** waiting on physical wiring — nothing is plugged into the Pi yet.
The ADS1115 driver, both sensor reads, and `calibrate_ph.py` remain verified only in terms of
their math, never against physical probes. Next session, in order: wire the ADS1115 (VIN to
**3.3V**, not 5V — see the voltage note above), confirm `i2cdetect -y 1` shows `48`, use
`read_adc.py` to sanity-check raw voltages and pin down the EC range variant, run
`calibrate_ph.py` against pH 4.00 and 9.18 buffers, paste the slope/intercept into `config.py`,
then `test_ph_sync.py` for a real end-to-end reading.
