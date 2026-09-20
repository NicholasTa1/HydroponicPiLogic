# Raspberry Pi Control Subsystem — Spec

Handoff document for the Pi-side software of the Next Generation Desktop Hydroponic capstone.
Everything below is my subsystem. Computer vision is owned by a teammate and runs on the same Pi
but is out of scope for this document.

---

## 1. Physical system

Baseline is a CropKing NFT Desktop System that we are instrumenting and automating.

| Property | Value |
|---|---|
| Plant sites | 8 |
| Crop | Lettuce |
| Reservoir volume | 2.5 gal / ~9.5 L |
| Circulation pump | 70 gph / ~4.4 L/min |
| Nominal tank turnover | ~2 min |
| Realistic mix time | ~10 min (3 to 5 turnovers plus channel transit) |
| Crop cycle | ~5 weeks from transplant to harvest |

**Why the small reservoir dominates every design decision:** water loss to transpiration scales
with leaf area, so it ramps hard across the cycle.

| Week after transplant | Est. water loss |
|---|---|
| 1 | ~1.6 L/week |
| 2 | ~3.6 L/week |
| 3 | ~7 L/week |
| 4 | ~11 L/week |
| 5 | ~14 L/week |

By weeks 4 and 5 the system loses **more than a full tank volume per week**. Two consequences:

- The top-off reservoirs must be physically larger than the grow tank (plan ~15 L clean water
  for a week unattended at peak).
- Late in the cycle the top-off liquid *is* the nutrient program, not a correction to it. Plain
  water top-off would strip the solution. This is why we have two source reservoirs.

---

## 2. Hardware

| Component | Part | Interface |
|---|---|---|
| Controller | Raspberry Pi 4 or 5, 2GB | — |
| pH probe | Atlas Scientific EZO-pH | I2C |
| EC probe | Atlas Scientific EZO-EC | I2C |
| Water temp | DS18B20 | 1-Wire |
| Water level | TBD (load cell or ultrasonic) | GPIO / I2C |
| Dosing pumps | Peristaltic x2 (clean water, dilute nutrient) | GPIO relay |
| pH dosing | Peristaltic x1 (pH down) — phase 2 | GPIO relay |

Notes:

- EZO boards must be on **isolated** carriers. EC probes inject an AC signal, pH probes are very
  high impedance, and they interfere if they share a ground.
- All relays wired **normally open** so power loss and reboot both fail to pumps-off.
- No ESP32 in the current design. Safety is handled by reservoir sizing plus software limits
  (see §6). This is a deliberate, documented tradeoff.

---

## 3. Architecture

```
┌─────────────────────────────── Raspberry Pi ───────────────────────────────┐
│                                                                            │
│  sensors.py ──→ filter ──→ validity ──→ control.py (state machine)         │
│       │                                      │                             │
│       ↓                                      ↓                             │
│  SQLite (local source of truth)         dosing relays                      │
│       │                                                                    │
│       ├──→ sync.py ──(5 min batch)──→ Supabase                             │
│       └──→ ble.py ──(read-only live view)──→ phone in range                │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

**Control runs entirely locally.** The network is never in the control path. Supabase is for
history, dashboards, notifications, and remote commands only.

---

## 4. Sensing layer

Three independent rates. Do not conflate them.

| Activity | Rate |
|---|---|
| Sample sensors | every 30 s |
| Write to SQLite | every sample |
| Evaluate control decision | every 5 to 15 min |
| Batch push to Supabase | every 5 min |

### Filtering

Never make a control decision on a single reading.

1. Median of the last 5 samples (kills spikes from air bubbles and pump start transients)
2. Exponential moving average over the median series

Store raw, filtered, and the calibration constants in use at the time. All three.

### Temperature compensation — mandatory

- EC shifts ~2% per °C
- pH probe response is temperature dependent via the Nernst equation

Feed water temp into the EZO boards each read cycle and let them compensate. **The DS18B20 is
load-bearing for the control loop**, not just a plant metric. If it fails, EC and pH readings are
untrustworthy and the system should alarm rather than dose.

### Validity checks — run on every sample, before anything else

| Check | Rule | Action on fail |
|---|---|---|
| Range | pH outside 3–9, EC outside 0–5 mS/cm | Alarm, hold |
| Rate of change | pH moving >1.5 units in 30 s | Alarm, hold |
| Stuck | Identical value to 4 dp for 20 consecutive reads | Alarm, hold |
| Temp sensor | No reading or out of 0–40 °C | Alarm, hold |

A failed check means a broken probe, not an emergency. **Never dose on a failed validity check.**

---

## 5. Control logic

### State machine

```
IDLE → EVALUATE → DOSE → SETTLE → IDLE
                    ↓
                  ALARM (manual clear required)

MAINTENANCE (operator-triggered, suspends all dosing)
```

`MAINTENANCE` is required for the weekly reservoir change. Without it, a tank going from near-empty
to full in two minutes looks like a massive control excursion. It must also mark the data so the
discontinuity is explicable in analysis.

### Setpoints

pH is constant across the cycle. EC ramps with crop stage.

| Stage | EC target (mS/cm) | EC act band |
|---|---|---|
| Week 1–2 | 0.8 | <0.6 or >1.0 |
| Week 3 | 1.1 | <0.9 or >1.3 |
| Week 4–harvest | 1.3 | <1.1 or >1.5 |

| Parameter | Target | Act band |
|---|---|---|
| pH | 5.8 | <5.4 or >6.2 |
| Water temp | <21 °C / 70 °F | alarm only, no actuator yet |
| Level | 80% of capacity | refill below 70%, never exceed 85% |

Stage is keyed to days after transplant, set by the operator at cycle start.

### Decision rules

1. **Deadbands, not thresholds.** A target and a wider act band. Prevents rapid cycling when a
   reading hovers at the line.
2. **Small fixed increments.** Do not compute a dose intended to land exactly on target. The tank
   model is wrong and you will overshoot. Dose small, wait, re-read, repeat.
3. **Lockout after every dose: 15 minutes.** Derived from ~10 min real mix time plus margin. Keep
   sampling and logging during lockout, just ignore the values for control.
4. **Correct EC before pH.** They are coupled — nutrient addition moves pH, and pH down adds ions
   which raises EC. Sequence them, do not run two parallel controllers.
5. **Never dose clean water and nutrient in the same cycle.** If logic ever calls for both,
   something is wrong. Alarm instead of acting.
6. **Level is a constraint on every dose.** Check projected post-dose level before actuating. If a
   correction would exceed the max fill line, skip it and flag "needs full change" rather than
   dosing partially.

No drain actuator exists. This is fine because late-cycle transpiration keeps the tank well below
full. Weeks 1 and 2 are the only headroom-constrained period, and drift is slowest then.

### Weekly reservoir change

Full dump and refill weekly, tightening to every 5 days in the final two weeks. This is manual and
stays manual — it resets **composition**, which the controller cannot do.

The controller holds concentration and pH. It does **not** hold nutrient ratios. Lettuce takes
nitrate and potassium faster than calcium and sulfate, so composition drifts underneath a perfectly
flat EC reading. This is a real and documented limitation of the design, not a bug.

Software requirements around the change:
- Operator flips to `MAINTENANCE` before dumping
- Log the event explicitly as a marker row
- Re-baseline filters on exit, do not carry the EMA across the discontinuity

---

## 6. Safety

No hardware watchdog processor. Coverage comes from four layers:

1. **Reservoir sizing (primary).** The nutrient reservoir holds dilute solution, not concentrate,
   and is sized so that pumping its entire contents into the 9.5 L tank is survivable. Same for
   the acid reservoir. This bounds the consequence of *any* failure, including a failure of the
   software limits themselves.
2. **Normally-open relays.** Power loss and most crash modes leave pumps off.
3. **Software limits.** Max dose volume per event, max doses per hour, max pump on-time enforced
   in a separate thread from the control loop.
4. **systemd watchdog.** Restarts the process if it stops responding.

Additional interlocks:
- Do not dose if the circulation pump is off (would dump into a stagnant tank)
- Do not dose on any failed sensor validity check
- Do not dose in `MAINTENANCE` or `ALARM`

Probe drift: pH probes drift over weeks and ours sit submerged for a full crop cycle. Log raw
millivolts alongside converted pH so drift is visible in post-hoc analysis, and schedule a
recalibration reminder.

---

## 7. Local storage

SQLite on the Pi is the **source of truth**. Writes happen every sample regardless of network
state.

Suggested tables:

```sql
readings (
  id, ts, sensor, raw, filtered, temp_c, calib_ref, synced BOOL
)

dose_events (
  id, ts, pump, volume_ml, duration_ms, trigger_param,
  trigger_value, target_value, synced BOOL
)

decisions (
  id, ts, param, value, in_band BOOL, action, reason, synced BOOL
)

state_changes (
  id, ts, from_state, to_state, note, synced BOOL
)

alarms (
  id, ts, kind, detail, cleared_ts, synced BOOL
)
```

**Log non-actions.** A row saying "evaluated, pH 5.9, within band, no action" sounds redundant but
it proves the controller was awake and reasoning during quiet periods. Reviewers ask about this.

Retention: keep full 30 s resolution locally for the entire crop cycle. That is ~100k rows per
sensor over five weeks, trivial for SQLite. **Do not downsample or purge the local copy until the
cycle is complete and exported** — the capstone analysis needs raw data.

---

## 8. Supabase sync

Free tier. Batch push every 5 minutes.

**Treat it as a queue, not fire-and-forget.** This is the single most important detail in this
section.

- Rows carry a `synced` flag, default false
- Each push sends everything unsynced, capped at a few hundred rows per request
- Mark rows synced **only after the server acknowledges**
- Loop until the queue drains
- A six-hour outage results in zero data loss, just a delayed catch-up

Do **not** clear local tables after transmission. Local retention and sync status are separate
concerns.

### Out-of-band events

Telemetry batches on the 5-minute cadence. These push **immediately**:

- Dose events
- Alarms
- Sensor faults
- State transitions

### Remote commands

The app can request a manual dose. Treat it as a **request, not an instruction**:

- Pi validates against the exact same interlocks that govern automatic dosing
- Pi rejects anything that would violate a bound, and reports the rejection
- Commands carry a timestamp and **expire**. A command queued while the Pi was offline and
  arriving 40 minutes later must be discarded, not executed
- The phone never drives a relay. The Pi is always the authority

### App to server

The app subscribes via Supabase realtime rather than polling. If polling is used as a fallback,
30 s foregrounded and stop entirely when backgrounded.

### Server-side retention

Full resolution for the recent window, downsample older data to 5 or 15 minute averages via a
scheduled job. Fine granularity matters around dose events; nobody needs 30 s resolution on a
growth curve from three cycles ago.

---

## 9. BLE live view

Read-only. When a phone is in range, broadcast a trimmed packet with current values only —
EC, pH, temp, level, state. No history, no commands, no writes.

Purpose is a glanceable local readout that works when WiFi is down. It is explicitly **not** a
control path.

---

## 10. Out of scope for this subsystem

- **Computer vision.** Teammate-owned. Runs on the same Pi, captures hourly, segments canopy via
  Excess Green index, writes projected leaf area per plant site. It reads nothing from the control
  loop and the control loop reads nothing from it. Only coupling is shared Pi resources and a
  shared timestamp basis for later correlation.
- Frontend/app UI
- Mechanical build, plumbing, light rig

---

## 11. Open items

- Level sensor part not yet selected (load cell vs ultrasonic). Load cell gives mass, which is a
  cleaner transpiration signal; ultrasonic is easier to mount.
- pH dosing is phase 2. Get clean water and nutrient dosing working and validated first. pH
  dosing is fiddlier and easier to get wrong.
- Dissolved oxygen sensing is desirable for NFT but probes are $150+. Check whether the lab has one
  before budgeting.
- Flow rate verification is currently manual and weekly. Worth automating if time allows — NFT
  fails quietly when a channel partially clogs and the film goes patchy.

---

## 12. Build order

Validated control loop beats a polished app on top of unvalidated logic. Sequence:

1. Sensor reads + filtering + validity checks + SQLite logging
2. Manual-only dosing via local CLI, with all interlocks live
3. Automatic control loop, clean water and nutrient only
4. Supabase sync with the queue semantics above
5. Remote command handling
6. BLE live view
7. pH dosing
8. Anything else

Start logging from day one even before the loop is automated. Week 1 data cannot be collected
retroactively.
