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

| Sensor | Part | Status as of 2026-11-16 |
|---|---|---|
| ADC | ADS1115 | **Working** — was never damaged; the fault was the analog ground reference |
| pH | DFRobot SEN0161/9 | **Reading, accuracy uncertain** — calibrated 2026-11-15, constants live in config.py. Span is ~40 mV/pH; see the 2026-11-15 entries |
| Light | VEML7700 | **Working** — initial failure was wiring |
| EC | Bluelab Guardian (Edenic API) | **Working** — live reading confirmed 2026-11-18 with the Guardian powered on |
| Water level | DFRobot SEN0204 | **Working** — 12k/22k divider, and a shared ground |
| Water temp | DS18B20 | **Working** — needed 1-Wire enabling via raspi-config + reboot |
| CO2 / air temp / humidity | SCD41 | **Blocked** — first unit dead on arrival, awaiting replacement |
| BLE transfer | — | **Working** — verified end to end with nRF Connect |
| Fan | Same Sky CFM-A2SG | **Code ready, nothing wired** — needs 12V, a MOSFET or relay, and a shared ground |
| Valve | NITRA via relay (`camera.py`) | **Unverified here** — separate script, and it disagrees with config.py about the level sensor's pin |

Note the distinction between **not working** and **not yet tested**. The fan has never been
driven and the Guardian has never produced a live reading, but neither is a software fault:
both are waiting on hardware. Nobody should go looking for bugs in their code until each has
been connected and produced at least one value.

The SCD41 blocks more than its own three columns: `temperature` is what drives the fan loop,
so until it is replaced the fan has no input and will sit in its 10-minute failsafe.

## 2026-11-09
- **EC moved from the analog SenseCAP probe to a Bluelab Guardian read over the Edenic cloud
  API.** The SenseCAP was never testable (its cable had no exposed conductors). Edenic already
  reports mS/cm, so no conversion is needed, and the Guardian does its own temperature
  compensation.
- Edenic publishes no official API documentation. Endpoints, auth and response shape were taken
  from the Home Assistant integration at github.com/plumbobdev/homeassistant-edenic:
  `GET {base}/telemetry/{device_id}` and `GET {base}/device/{org_id}`, base
  `https://api.edenic.io/api/v1`, with the raw API key in an `Authorization` header and values
  returned as strings in a newest-first list. Treat all of that as unofficial.
- **Rate limit vs sample rate:** Edenic allows roughly one request per minute while the control
  loop samples every 30s, so telemetry is cached for `EDENIC_MIN_POLL_S` and served from cache
  in between. Verified this holds to exactly one call per minute under a 30s loop. HTTP 400 is
  Edenic's rate-limit response and is surfaced with that explanation rather than as a generic
  error.
- **This puts the internet in the control path for EC, contrary to spec §3** ("the network is
  never in the control path"). Dosing decisions that depend on EC will stop working during an
  outage. A failed fetch raises, so the loop records a fault and leaves EC NULL — it degrades
  to "no reading" rather than acting on a stale one, which is the safe direction. Worth
  revisiting if dosing is automated: the Guardian has a local display, but no local API.
- **API keys expire after one year.** EC will start faulting with no other warning when it does.
- Credentials (`EDENIC_API_KEY`, `EDENIC_ORGANIZATION_ID`, `EDENIC_DEVICE_ID`) live in `.env`,
  never in config.py. Added `list_edenic_devices.py` to find the device id.
- Old analog EC constants are kept in config.py but unused, in case that path is revived.

## Reference: grounding

**Three separate sensor faults on this project have turned out to be grounding.** Before
debugging anything else on a new sensor, confirm its ground is physically tied to the Pi's.

A voltage only means anything relative to a reference. A sensor on its own supply — however
clean and reliable that supply is — produces readings the Pi cannot interpret unless the two
share a ground. The symptoms look like everything except what they are:

| Sensor | Looked like | Actually was |
|---|---|---|
| SCD41 | Dead device, absent from `i2cdetect` | External 5V supply ground not tied to Pi |
| ADS1115 | Damaged chip: config read back fine, all channels garbage | Analog ground reference, same cause. Chip was fine |
| SEN0204 | Marginal logic level, random HIGH/LOW with a correct LED | External supply ground not tied to Pi |

The tell for the water level sensor was **random** switching rather than a regular pattern.
A marginal voltage gives something rhythmic or noise-correlated; a floating reference gives
randomness. Worth remembering, because the divider maths looked right the whole time and the
sensor's own LED was correct throughout — everything pointed away from the real cause.

A useful test needing no multimeter: jumper the GPIO straight to 3.3V, then to GND. Both
should read rock solid. If they do, the Pi input is fine and the fault is in the signal path.

## Reference: running on the Pi

```bash
cd ~/HydroponicPiLogic/pi
source .venv/bin/activate          # create once: python3 -m venv .venv
pip install -r requirements.txt    # supabase, python-dotenv, smbus2, gpiozero, bless

i2cdetect -y 1                     # expect 48, 62, 10 for whatever is wired
ls /sys/bus/w1/devices/            # expect a 28-* entry for the DS18B20

python3 read_adc.py                # live ADC voltages (pH/EC), Ctrl-C to stop
python3 read_sensors.py            # every sensor, converted values -- the main bring-up tool
python3 calibrate_ph.py            # needs two buffers, e.g. pH 4.00 + 7.00
python3 list_edenic_devices.py     # Guardian device ids, once .env has key + org id
python3 compare_ph.py --watch      # testing only: DFRobot pH vs the Guardian's, logged
python3 test_fan.py                # cycles the fan on/off, to check relay wiring
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

## 2026-11-03
- **Local storage is now one wide row per 30s cycle instead of one row per reading.**
  `readings` has one column per sensor (`ph`, `ec`, `water_level`, `temperature`, `water_temp`,
  `humidity`, `co2`, `light`) plus `ts`, `basin_id`, `synced`. Why: Supabase and the BLE app
  both want one row per cycle, and each had to rebuild cycles from individual readings; BLE did
  it by guessing from timestamp gaps, which long pH settling waits could break. Supabase now
  gets one complete row per cycle instead of one mostly-null row per reading.
- **A reading that fails validity, or a sensor that raises, is NULL in the row and recorded in
  a new `faults` table** (`ts`, `basin_id`, `sensor`, raw `value`, `reason`). This keeps the
  spec §7 record of bad readings that the old `valid`/`invalid_reason` columns held. Faults
  never sync. A sensor raising `NotImplementedError` (not wired) is just NULL, not a fault.
- Master-basin values (pH, EC, water level) are read once per cycle and written into every grow
  basin's row. With one basin there is no duplication; with more, they repeat per row.
- **Migration:** on first start, an old long-format `readings` table is renamed to
  `readings_long` (data kept, nothing reads or syncs it). Any of its rows still unsynced at
  that point will not upload. Once confirmed unneeded: `sqlite3 hydro.db "DROP TABLE readings_long;"`
- Trade-offs accepted: each row has one timestamp (the cycle start), not one per sensor; a
  crash mid-cycle loses that cycle's good readings, since the row is written at the end
  (faults are committed immediately).
- Updated `sync.py`, `ble_protocol.py`/`ble_server.py` (no more cycle grouping),
  `seed_dummy_data.py`, `test_ph_sync.py`, and `docs/ble-protocol.md`. The BLE wire format
  is unchanged. Checked off-Pi against a scratch database (migration, a cycle with an invalid
  and an erroring sensor, sync record mapping, BLE messages); not yet run on the Pi or against
  Supabase.
- Still open: `sensor_readings` has no `basin_id`, so a second basin cannot be told apart
  remotely. Spotted in passing: `ble_server.py` opens the database read-only, so if it starts
  before `main.py` has migrated an old database, BLE requests fail with `db busy` until
  `main.py` runs once.

**Stopped here (2026-10-01):** waiting on physical wiring — nothing is plugged into the Pi yet.
The ADS1115 driver, both sensor reads, and `calibrate_ph.py` remain verified only in terms of
their math, never against physical probes. Next session, in order: wire the ADS1115 (VIN to
**3.3V**, not 5V — see the voltage note above), confirm `i2cdetect -y 1` shows `48`, use
`read_adc.py` to sanity-check raw voltages and pin down the EC range variant, run
`calibrate_ph.py` against pH 4.00 and 9.18 buffers, paste the slope/intercept into `config.py`,
then `test_ph_sync.py` for a real end-to-end reading.

## 2026-11-07
- **BLE transfer now includes water temperature.** `ble_protocol.COLUMNS` gained `water_temp`
  (°C, from the DS18B20). Why: it was already measured, stored locally and synced to Supabase
  via `REMOTE_COLUMNS`, but the BLE snapshot silently dropped it because `COLUMNS` didn't list
  it, so the app showed "—" for water temperature whenever it synced over Bluetooth.
- Appended as the **last** column so every existing position is unchanged. A client reading
  values positionally by the old 7-column layout still gets the right values; the app maps
  values by the `cols` names in the header, so it picks the new column up without changes.
- Updated `docs/ble-protocol.md` and `docs/ble-app-plan.md` (header example, row example,
  columns table), and dropped the stale "no app column" comment in `seed_dummy_data.py`.
- Checked off-Pi: `build_messages` emits 8 columns with `water_temp` last, and a row stays far
  under the 500-byte notification limit. Not yet run on the Pi.
- The app repo keeps its own copy of `ble-protocol.md`; it needs the same update.

### Water level now leaves the Pi (for in-app overflow alerts)
- **`water_level` syncs to Supabase and is sent over BLE**, so the app can warn about an
  overflow. Mapped in `REMOTE_COLUMNS`; BLE `COLUMNS` gained it as the last column (9 now).
- **Sent as true/false, not 0.0/1.0.** SQLite stores every sensor as REAL, so the new
  `config.BOOLEAN_COLUMNS` and `remote_value()` convert it on the way out. Both `sync.py` and
  `ble_protocol.snapshot()` use the same helper, so the two paths can't disagree.
- **Meaning:** `true` = water has reached the SEN0204, which is mounted at the overflow height.
  Still unverified on the bench (the sensor is "not yet tested" above), including whether this
  module's output is inverted. Check by hand before trusting an alert.
- **Supabase needs the column first.** `supabase_schema.sql` has the one-line
  `alter table ... add column water_level boolean`; until it is run, every sync insert fails
  because the payload carries a column the table doesn't have.
- This is the in-app-only version: the app shows the alert while it is open. No debounce or
  pump cut-off on the Pi yet, and no push notifications — both still open.
- Checked off-Pi with a stubbed `dotenv`/`supabase`: 1.0 → `true`, 0.0 → `false`, missing →
  `null`, identically in the sync record and the BLE row.


## 2026-11-09
- **Checked what sync sends against the live `sensor_readings` table.** The table has `id`,
  `recorded_at`, `ph`, `ec`, `water_temp`, `temperature_c`, `humidity`, `light_intensity`, `co2`,
  `username`, `water_level`. Every column sync sends exists there. The one gap was `username`:
  nothing filled it, and the app shows a signed-in user only rows tagged with their username, so
  every row the Pi uploaded was invisible in the app.
- **Sync now tags every row with a placeholder username**, `config.SUPABASE_USERNAME`, default
  `admin` (the app's test login), overridable via `SUPABASE_USERNAME` in `.env`. It is a
  placeholder until the app moves to Supabase Auth; it is not sensor data.
- Sensors with no reading still sync as `null`. Nothing is faked into the dataset.
- The 40 rows currently in the table (ids 92-131) are seeded test data, all `admin`; earlier Pi
  test rows (ids 12-16) are gone.
- Checked off-Pi with a stubbed `supabase`: the record's keys match the table's columns
  exactly (`id` excepted), and an all-empty cycle is still skipped. Not yet run against Supabase.
- **The level sensor has moved to the low-water mark** (the app now alerts on low water, not
  overflow). `true` still means water at the sensor, so nothing changes on the Pi, but the
  "overflow height" wording in `config.py`, `docs/ble-protocol.md` and the entry above is out of
  date. Rows uploaded while it sat at the overflow height read `false` and now look like low water.

## 2026-11-09 (later)
- **Cause of the "445.0 is not a valid value" sync error:** the `sensor_readings` table was
  recreated by a CSV import, which inferred `co2` as `bigint` from the CSV's whole-number values.
  The Pi stores every reading as REAL and sent `445.0`; Postgres rejects that for a bigint
  (`invalid input syntax for type bigint: "445.0"`), and because a batch is one insert, the
  whole batch failed, not just CO2. Every other numeric column still accepts decimals.
- **Fix:** new `config.INTEGER_COLUMNS = {"co2"}`; `remote_value()` sends those as ints, for
  both Supabase and BLE. The SCD41 only reports whole ppm, so nothing is lost. Alternatively
  the column can go back to decimals with
  `alter table sensor_readings alter column co2 type double precision;`; either works.
- **`system_name` now sent on every row**, from `config.SYSTEM_NAME` (`HYDRO_SYSTEM_NAME` in
  `.env`, default "Tower A"). The app now builds one system per distinct `system_name`; untagged
  rows land under "Unassigned". Also appended as the last BLE column, so Bluetooth rows are filed
  under the right system too. Each Pi needs its own name.
- Updated `docs/ble-protocol.md` (new column, co2 as integer, `water_level` now means water at
  the low-water mark). The app repo's copy of `ble-protocol.md` is out of date; the app maps BLE
  columns by name, so it needs no code change.
- Checked off-Pi with a stubbed `supabase`: the record's keys match the live table's columns
  exactly, co2 serializes as `445`, BLE rows have 10 values and stay under 160 bytes. Not yet
  run on the Pi or against Supabase.
- Updated the VEML7700 maximum value to 100k, since readings with the grow lights were over 30k.

## 2026-11-11
- **BLE now sends exactly the columns Supabase sync sends.** The only gap was `username`, now
  appended as the last BLE column (11 columns), so existing positions don't move.
- **One builder for both paths:** new `config.remote_record(row)` builds the remote record
  (`recorded_at`, `username`, `system_name`, and every `REMOTE_COLUMNS` sensor value with
  `remote_value()` applied). `sync._row_to_record()` and `ble_protocol.snapshot()` both use it,
  replacing two hand-built copies that had drifted.
- **Drift guard:** `config.REMOTE_RECORD_COLUMNS` lists the record's columns, and
  `ble_protocol.py` raises at import if `COLUMNS` doesn't contain exactly those. A column added
  to sync now fails loudly until it's also appended to the BLE contract, instead of being
  silently dropped from Bluetooth.
- The app needs no change: it maps BLE values by column name and ignores `username`. Its copy
  of `ble-protocol.md` is still out of date.
- Checked off-Pi with a stubbed `supabase`: a BLE row and a sync record for the same cycle
  carry identical keys and values, an all-empty cycle is still skipped by sync, and the largest
  BLE message stays well under 500 bytes. Not yet run on the Pi.

## 2026-11-11 (later)
- **Each Pi now names itself from its hardware.** Default `system_name` and Bluetooth advertised
  name are both `HydroPi-<first 8 hex digits of SHA-256 of the hardware id>` (e.g.
  `HydroPi-3f9a0c12`), replacing the "Tower A" default and `HydroPi-<hostname>`. One name for
  both means the app can match a nearby Pi to its system.
- **Hardware id:** the SoC serial from `/sys/firmware/devicetree/base/serial-number` (Pi 4 and
  5), else `Serial` in `/proc/cpuinfo`. Unique per board and survives reflashing. Off-Pi fallbacks
  for development: `/etc/machine-id` (changes on OS reinstall), then the MAC, then the hostname.
  All-zero serials (some VMs) are skipped. `main.py` prints the name and its source at startup.
- `HYDRO_SYSTEM_NAME` in `.env` still overrides the system name (not the BLE name). It is now
  commented out in `.env.example`, so copying the example no longer pins every Pi to "Tower A".
- **Deploy note:** a Pi whose `.env` sets `HYDRO_SYSTEM_NAME` keeps that name; remove the line to
  switch to the hashed name. Rows already uploaded under "Tower A" stay under that name, so the
  app will show the Pi as a new system from the switch onward.
- 8 hex digits = 32 bits. Chance any two Pis share a name: ~1 in 1.4 billion for 3 Pis,
  ~1 in 870,000 for 100, ~1 in 8,600 for 1,000. Lengthen DEVICE_HASH_LENGTH if the fleet ever
  reaches thousands. The name identifies a Pi; it is not a secret (serials are guessable).
- Checked off-Pi with faked id files: serial preferred over cpuinfo and machine-id, all-zero
  serials skipped, same serial always gives the same name, override honoured. Not yet run on a Pi.

## 2026-11-15
- **`calibrate_ph.py` now rejects an implausible slope instead of printing it.** The previous
  run produced `PH_SLOPE = 25.7373` / `PH_INTERCEPT = -18.0681` from pH 4 at 0.857 V and pH 7
  at 0.974 V: a span of 0.117 V over 3 pH units, or **39 mV/pH against this board's nominal
  286** — 14% of a healthy electrode. The only acceptance test was "the two buffers differ by
  more than 0.01 V", which 0.117 V passes easily, so the script printed constants that look
  like a calibration and would have turned every later pH reading into noise.
- The gate is on the fitted slope, not on absolute voltage, so it holds for any buffer pair:
  outside **2.0-6.0 pH/V** (generous either side of the nominal 3.5) the script explains the
  failure and returns without printing, unless the operator types `force`. It also now reports
  mV/pH and the percentage of nominal on every run, pass or fail, since that single number is
  what distinguishes a tired electrode from a wiring fault.
- Also noted in the rejection message that **the offset potentiometer cannot fix a compressed
  span** — it shifts the curve, not its slope. Worth stating because the pot having "seemingly
  random effect" was the previous session's most visible symptom and is a dead end for this.
- Checked off-Pi with the ADC stubbed: the previous run's voltages are rejected with
  `slope 25.6410`, and a healthy 1.143 V / 2.000 V pair still passes, yielding
  `PH_SLOPE = 3.5006` / `PH_INTERCEPT = -0.0012` exactly as before.
- Fixed a stale "pH 4.00 + 9.18 buffers" line in the run-on-the-Pi reference; the buffers on
  hand are 4.00 and 7.00. The identical line inside the 2026-10 entry is left as history.

### The compressed pH span
A second calibration run gave slope 25.1572 / intercept -18.6824, against 25.7373 / -18.0681
the time before. Backing the voltages out of both:

| run | V @ pH 4 | V @ pH 7 | span | mV/pH |
|---|---|---|---|---|
| first | 0.8574 | 0.9740 | 0.1166 | 38.9 |
| second | 0.9016 | 1.0209 | 0.1193 | 39.8 |

**The span reproduced to within 2.3%, and the offset moved by 0.045 V.** Both are informative:
a repeatable linear response is not a floating reference (that gave *randomness* on the level
sensor, which is what identified it), so grounding was ruled out here. The offset moving while
the span held is the potentiometer doing exactly what a pot does, which confirms absolute
voltage says nothing about probe health on this board -- only the span does.

Whether 39.8 mV/pH is fatal depends on the board: a bare glass electrode gives 59.16 mV/pH
(Nernst, 25 C), so it is 67% of a *buffered* board's nominal but only 14% of an *amplified*
one's 286 mV/pH. Which board is in use was never recorded beyond "SEN0161/SEN0169", and the
distinction matters for every reading, so it is worth pinning down if pH is revisited.

**Resolved on the bench 2026-11-15; the cause was not shared with this session, so it is not
recorded here.** Anyone picking pH up again should ask rather than re-derive from the above.

## 2026-11-15 (later)
- **Removed the slope plausibility gate from `calibrate_ph.py`**, added earlier the same day.
  It rejected anything outside 2.0-6.0 pH/V, a range derived from DFRobot's `pH = 3.5 x V`,
  which assumes an amplified board. The boards sold under these part numbers are not all
  amplified -- a buffered one sits near 17 pH/V -- so on the wrong board the gate would have
  rejected every valid calibration and forced an operator through a `force` prompt each time.
  Guessing at the hardware was worse than not checking.
- What remains is the span report, now stated plainly as `span 0.1193 V over 3.00 pH =
  40 mV/pH` with no judgement attached, so it can be compared against whichever board is
  actually wired. The pre-existing "both buffers read the same voltage" check also stays: that
  one needs no assumption about gain, since no board of any kind reports a dead flat response.
- Checked off-Pi with the ADC stubbed: the run that was rejected now prints its constants, an
  amplified board still yields 3.5006 / -0.0012, and two identical readings are still caught.
- **The second run's constants are now live in `config.py`** (`PH_SLOPE = 25.1572`,
  `PH_INTERCEPT = -18.6824`, committed separately as 720a404; the 3.5 / 0.0 defaults are left
  commented out above them). Accepting a 40 mV/pH response as correct implies the board
  buffers the electrode rather than amplifying it, which is the reading of the table above
  that puts the probe at ~67% efficiency rather than 14%. That also settles why the gate
  removed in this commit had to go: it would have rejected the constants now in use.
- **~67% is still below the ~85% that normally retires a glass electrode**, so expect pH
  accuracy to drift and the probe to need replacing sooner than the others. Worth a second
  opinion against a handheld meter before trusting pH for dosing decisions.

## 2026-11-15 (id)
- **The Pi now sends `id` on every row**, taken from the local SQLite `readings` counter
  (`INTEGER PRIMARY KEY AUTOINCREMENT`, so 1, 2, 3, ...) rather than letting Postgres generate
  it. Added to `config.remote_record()` and `REMOTE_RECORD_COLUMNS`, so it goes to Supabase and
  over BLE from one builder; appended last in `ble_protocol.COLUMNS`, keeping every existing
  position unchanged. `docs/ble-protocol.md` updated (the app repo's copy is still behind).
- Sent as a plain int, not via `remote_value()`: it is a row identifier, not a sensor reading,
  so it needs none of the boolean/integer conversions. All-empty cycles are still skipped by
  sync, because the skip test only looks at `REMOTE_COLUMNS` values.
- Checked off-Pi against a real SQLite file with `supabase` stubbed: ids 1-3 arrive in the
  insert payload as integers, a sync record and a BLE row for the same cycle stay identical,
  and the largest BLE message is 176 bytes. Not yet run against Supabase.

### Caveat: this id is only unique within one Pi
`id` is the table's primary key, and a local counter is not globally unique. Three ways it
collides, each of which fails the **entire** insert batch, not the one row — the same
batch-poisoning that the `co2` bigint and `water_temp` array problems caused:
1. **A second Pi.** `system_name` was added precisely because there will be more than one
   system, and every Pi's counter starts at 1.
2. **A wiped or recreated `hydro.db`.** Ids restart at 1 and collide with everything already
   uploaded.
3. **Rows the database generated itself.** The seeded rows currently occupy ids 92-131, so a
   Pi starting from 1 collides on reaching 92. An identity sequence also does not advance when
   ids are supplied explicitly, so anything still inserting without an id will eventually
   reissue ids the Pi has already used.
A collision does not drop one reading: the batch never succeeds, those rows stay unsynced, and
sync retries the same failing batch forever, so uploading stops until someone intervenes.
`supabase_schema.sql` records the one-line `alter table` to hand id generation back to Postgres
if that is preferred. Not changed either way here — sending it was asked for deliberately.

## 2026-11-15 (first-cycle sync)
- **`main.py` now syncs straight after the first read cycle** instead of five minutes in.
  `last_sync` starts as `None` rather than `time.monotonic()`, so the interval check passes on
  the first pass and is then set normally. The 5-minute cadence is unchanged after that.
- Why: a bring-up run proves the whole pipeline — sensors, validity, SQLite, Supabase — in one
  30s cycle instead of making someone wait out `SYNC_INTERVAL_S` to find out a credential is
  wrong. A restart also pushes out whatever the previous run left unsynced right away, rather
  than holding it for another interval.
- A failed first sync still sets `last_sync`, so the retry is on the normal 5-minute cadence,
  exactly as before. No change to how failures are handled.
- Checked off-Pi with `read_all`/`sync_pending` stubbed over 4 cycles: sync runs on cycle 1 and
  on none of cycles 2-4.
- Note for bring-up: `sync_pending()` prints only on failure, so a successful first sync is
  silent. Confirm it in Supabase, or ask for a log line if that is wanted.

## 2026-11-15 (fan control)
- **The fan loop now actually drives a pin.** `control.FanController` had the hysteresis logic
  but ended in `TODO: drive the actual relay/GPIO pin`, so nothing switched. It now holds a
  lazily-built `gpiozero.DigitalOutputDevice` on `FAN_GPIO_PINS[basin_id]` (BCM **27**; 11, 17
  and 19 are taken, plus 2/3 for I2C and 4 for 1-Wire), built on first use so constructing a
  controller stays side-effect free off a Pi.
- `FAN_RELAY_ACTIVE_HIGH` covers active-LOW relay boards, which are the common kind. Set wrong
  it runs the fan exactly when it should be off, so `test_fan.py` was added to check it: it
  cycles the fan 5s on, 5s off, and the fan should spin while the terminal says ON.

### The 58 F off-threshold could never have worked
`FAN_OFF_TEMP_F` was 58 F against an ON of 72 F. The fan exhausts to room air, so the chamber
cannot get far below ambient; in a ~70 F room, 58 F is unreachable, and the fan would latch on
at the first warm moment and run forever. **Changed to 69 F**, leaving a 3 F band -- ample to
stop a fan chattering at a threshold that is only sampled every 30s. ON stays at the 72 F
originally specified, which is conservative for lettuce: it wants 60-70 F air and starts
bolting, tipburning and going bitter above ~75 F. Nothing in `PI_CONTROL_SPEC.md` covers fans,
so 72/58 came from the original brief and not from the spec.

### A dead temperature sensor no longer disables cooling
`main.py` used to drop a failed reading before the controller saw it, holding the fan wherever
it was. That is right for a one-off glitch and wrong for a sensor that has died, because the
hold never ends -- and the SCD41 that provides this reading has already been DOA once. The None
is now passed through to `FanController.update()`, which holds for `FAN_STALE_READING_S`
(10 min = 20 missed cycles) and then runs the fan until a trusted reading says otherwise. The
two failure directions are not equal: a fan stuck off cooks the crop, a fan stuck on costs a
little power and noise.

### Wiring, from the CFM-A2SG datasheet
- **12 Vdc** (10.8-13.2 V), 0.08-0.47 A typical by model, 0.56 A max on the 3000 RPM variant.
  A Pi GPIO is 3.3V at a few mA and the Pi has no 12V rail, so the pin switches a MOSFET or
  relay in the fan's negative lead -- it does not power the fan. **The 12V supply's ground must
  be tied to the Pi's**: see the grounding section above, three faults on this build so far.
- **Do not PWM the supply line to vary speed.** Starting voltage is 7V, so the fan stalls
  rather than slows. Speed control needs the blue PWM wire, present only on `-22` part numbers,
  at 10-60 kHz with VIH 2.5-6V (the Pi's 3.3V qualifies). This code only switches fully on/off.
- Unused for now but available: tach on the yellow wire of `-20`/`-22` models, open collector,
  so it needs a pullup to 3.3V (Ic <= 5 mA means R >= 660 ohm; 10k is fine). The motor is
  4-pole, 2 pulses per revolution, RPM = Hz x 30. That would let the Pi detect a failed fan,
  which the bang-bang loop currently cannot.
- Auto-restart on a locked rotor is built into the fan. Soft start (~15s ramp) only on the
  -130-431.
- On exit gpiozero resets the pin, so the fan stops. Failing *on* would be the safer direction
  for the crop; that needs a normally-closed relay, which is a hardware choice, not a code one.
- Checked off-Pi with the pin stubbed: the fan switches on above 72 F, holds through 71/70/69.5
  on the way down, releases below 69 F, stays off for 9 min of unreadable temperature, runs at
  10 min, and returns to normal control when a trusted reading comes back. **Not yet run on a
  Pi, and no fan has been wired** -- the thresholds and the relay polarity are both unverified
  against real hardware.

## 2026-11-15 (fan thresholds)
- **`FAN_ON_TEMP_F` raised 72 -> 74 F; `FAN_OFF_TEMP_F` stays at 69 F**, so the hysteresis band
  is now 5 F. Asked for directly: less eager to start the fan, same point to stop it.
- 74 F still sits under the ~75 F where lettuce bolts, tipburns and turns bitter, which is the
  failure that ends a crop rather than merely slowing it. Raising ON further would mean cooling
  only after the crop is already in that range.
- **What the wider band changes:** once tripped, the fan now runs from 74 F down to 69 F
  instead of 72 F down to 69 F, so expect fewer, longer runs rather than more frequent short
  ones. That is the right trade for a fan (cycling is cheap, there is no compressor to protect).
- **What it does not change:** the fan exhausts to room air, so it cannot pull the chamber far
  below ambient. In a room at or above ~69 F the OFF threshold is unreachable and the fan will
  latch on and stay on, exactly as the old 58 F did, just less obviously. Which regime this
  system is in is an empirical question and nobody has the data yet -- the SCD41 that provides
  `temperature` has been DOA since 2026-10, so the fan loop has never seen a real reading.
- **Tune from the log, not from guesses.** `temperature_c` is already synced every 30s; a day
  or two of it under the grow lights will show whether the chamber ever reaches 69 F at all. If
  it does not, the answer is not a different threshold but less heat input or a cooler room.
- Checked off-Pi: fan trips on above 74 F, holds through 73/71/69.5 on the way down, releases
  below 69 F. Still not run on a Pi, and still no fan wired.

## 2026-11-16
- **The Edenic EC path is live and talking to the real API.** Credentials went into `pi/.env`
  (gitignored, never committed) and `list_edenic_devices.py` returned four Guardian Wi-Fi units
  on the organisation: `PSU-IPPL-VF-01`, `-VF-02`, `-GH01`, `-GH02`. This system is
  **PSU-IPPL-VF-01**; its device id is in `.env` as `EDENIC_DEVICE_ID`. The organisation is
  shared lab equipment, so picking the wrong one would quietly log another greenhouse's EC into
  this dataset -- confirm the label before changing it.
- `list_edenic_devices.py` was showing the wrong field: the API's `name` is an internal
  `organisation__serial` string, while `label` is the name shown in the Edenic app. Now prints
  `label` first.
- Telemetry confirmed working end to end: `ECSensor.read()` returned 0.42 mS/cm, the 60s cache
  served a second read with no network call, and the value passed the §4 range check. The
  Guardian also publishes `ph` and `temperature` on the same endpoint, which nothing reads.

### The API reports stale data as if it were current
The first real reading was **6.7 days old** — PSU-IPPL-VF-01 has been unplugged since
2026-11-09 18:40. The endpoint answered 200 with the last sample it ever received and no
indication the device had stopped, so the Pi would have logged a week-old number as a live
measurement every 30s. **This is the failure mode the 2026-11-09 entry claimed was handled**,
and it was not: that reasoning only covered a fetch that *fails*, and this one succeeds.
- **Fix:** `EdenicTelemetry.value()` now checks the sample's own `ts` and raises past
  `EDENIC_MAX_READING_AGE_S` (30 min), naming the device and the age. `_read_trusted` records
  it as a fault and leaves EC NULL, the same as any other sensor failure. Verified against the
  live API: `Edenic 'electrical_conductivity' is 161.0 h old (limit 30 min) — device ... has
  stopped reporting`, reading not trusted, fault row written.
- **The §4 stuck check is now off for `ec`.** It would have caught this eventually — 20
  identical readings is 10 minutes — but only after ten minutes of trusting week-old data, and
  it would have blamed a stuck probe rather than an offline device. It is also wrong in the
  other direction: the cloud value updates more slowly than the 30s sample loop, so identical
  consecutive readings are normal here. The timestamp check replaces it and is both faster and
  more specific.
- 30 min was chosen as well clear of the Guardian's reporting interval, which is not documented
  anywhere. If a healthy unit starts faulting as stale, raise `EDENIC_MAX_READING_AGE_S` rather
  than removing the check.
- Open: EC stays NULL until the Guardian is plugged back in. Worth one read then, to confirm a
  live value arrives and to see how often the timestamp actually advances.

## 2026-11-18
- **EC is working end to end.** With PSU-IPPL-VF-01 powered on, `ECSensor.read()` returned
  0.44 mS/cm from a sample 30s old, passing the §4 range check. This is the first live EC
  reading the system has ever taken — the analog SenseCAP it replaced was never testable.
- **Measured the Guardian's reporting interval**, which nothing documents: it posts **every
  60s, on the round minute**, with one 120s gap across six minutes of polling. Two
  consequences:
  - `EDENIC_MAX_READING_AGE_S` **cut from 1800 to 600**. 30 min was a guess made with no idea
    of the cadence; it is 30x the reporting interval, so a dead Guardian would have gone
    unnoticed for half an hour. 10 min still tolerates ~9 missed reports, which covers the
    120s gap seen and a Wi-Fi blip besides.
  - `EDENIC_MIN_POLL_S = 60` turns out to match the publish rate exactly, so the cache fetches
    each new sample about once. Nothing to change.
- **The `stuck_check: False` for `ec` is vindicated empirically.** EC read 0.44 unchanged for
  the whole six minutes while the timestamps advanced every minute — genuinely fresh data that
  happens to be stable. At the 30s sample rate that is 12+ identical readings already, and the
  check fires at 20, so a stable reservoir would have been reported as a dead probe within ten
  minutes.
- **The Guardian's pH probe is fine.** It read 13.69 while unplugged, which looked like a dead
  probe; powered on it reads 6.8. That value was an artifact of the offline state, not a fault.
- **Both Guardian values sit outside the spec §5 act bands**: EC 0.44 against a Week 1-2 target
  of 0.8 (act below 0.6), and pH 6.8 against a target of 5.8 (act above 6.2). Consistent with
  plain or freshly topped-up water rather than made-up nutrient solution. Worth confirming
  before reading anything into the numbers — if dosing existed, both would be calling for it.
- **Open opportunity:** the Guardian reports pH independently of the DFRobot probe on the ADC,
  and that probe's accuracy is still unresolved (40 mV/pH, never settled as 67% or 14% of
  nominal). Reading both in the same reservoir at the same moment would settle it. Needs to run
  on the Pi, where the ADC is; not written yet.

## 2026-11-18 (pH cross-check)
- **Added `pi/compare_ph.py`, testing only.** Nothing in `main.py`, `sync.py` or the BLE path
  imports it (checked by grep), and it writes to its own `ph_compare.csv` rather than
  `hydro.db`, so it cannot reach the recorded dataset.
- Why: the Guardian measures pH in the same reservoir, independently of the DFRobot probe on
  the ADC. That makes it the reference the buffer solutions could not be — the buffer
  calibration gave ~40 mV/pH and we never settled whether that is ~67% of a buffered board's
  nominal (tired but usable) or ~14% of an amplified board's (dead).
- Three modes: a single comparison, `--watch` to log a pair every 60s (the Guardian's publish
  rate), and `--fit` to least-squares fit `PH_SLOPE`/`PH_INTERCEPT` from the logged pairs with
  the Guardian as truth.
- **`--fit` needs pairs at two or more genuinely different pH values.** A slope cannot be
  fitted from readings all taken at one pH however many there are, so it refuses below a 1.0 pH
  spread rather than returning a number made of noise. Getting that spread means letting the
  reservoir drift or dosing it between runs. Done that way it calibrates against the Guardian
  and sidesteps the buffers entirely.
- A single comparison cannot separate a wrong slope from a wrong offset, so it reports only the
  intercept that would reconcile that one reading, and says as much.
- Checked off-Pi with synthetic pairs: a 59 mV/pH electrode fits to `PH_SLOPE = 16.9492`, a
  286 mV/pH one to `3.4965`, and a 40 mV/pH one to `25.0000` -- that last is essentially the
  25.1572 now in config.py, so if the fit lands near 25 the buffer calibration was right after
  all and the probe genuinely responds at 40 mV/pH.
- Fixed a bug in that output before committing: the mV/pH figure was the voltage span across
  the whole pH range rather than per pH unit, so it read exactly 2x high on a 2 pH spread.
- Not yet run on the Pi -- the ADC half needs real hardware.
