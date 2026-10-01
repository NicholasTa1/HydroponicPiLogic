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

**Stopped here (2026-10-01):** waiting on physical wiring — nothing is plugged into the Pi yet.
The ADS1115 driver, both sensor reads, and `calibrate_ph.py` remain verified only in terms of
their math, never against physical probes. Next session, in order: wire the ADS1115 (VIN to
**3.3V**, not 5V — see the voltage note above), confirm `i2cdetect -y 1` shows `48`, use
`read_adc.py` to sanity-check raw voltages and pin down the EC range variant, run
`calibrate_ph.py` against pH 4.00 and 9.18 buffers, paste the slope/intercept into `config.py`,
then `test_ph_sync.py` for a real end-to-end reading.
