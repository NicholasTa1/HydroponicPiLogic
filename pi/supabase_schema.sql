-- No table creation needed right now — `sensor_readings` already exists in the Supabase
-- project with this shape (confirmed via the REST API 2026-09-27):
--
--   id              bigint / identity, primary key
--   humidity        double precision
--   temperature_c   double precision
--   light_intensity double precision
--   ec              double precision
--   ph              double precision
--   recorded_at     timestamptz
--
-- A `co2` column was added 2026-10-03 and is mapped in sync.py; CO2 now syncs.
-- A `water_temp` column (double precision) exists as of 2026-10-13.
--
-- `water_level` (boolean, true = water at the overflow sensor) is mapped in config.py as of
-- 2026-11-07. The column must exist before sync.py sends it, or every insert fails. Run once
-- in the Supabase SQL editor:

alter table sensor_readings add column if not exists water_level boolean;

--
-- It has no basin_id column, so it only fits a single basin's worth of readings. sync.py
-- currently only maps the `ph` column (see _row_to_record). Once more basins/sensors need to
-- land remotely, this table will need a basin_id column added (or a rethink to a long/narrow
-- format matching the local SQLite `readings` table) — flagging here rather than deciding
-- unilaterally, since another table consumer (the app/CV side) may already depend on this shape.
