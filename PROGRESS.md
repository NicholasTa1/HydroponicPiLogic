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
