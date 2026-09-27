"""Central config for the Pi control subsystem. Tune values here, not in the modules."""

import os

from dotenv import load_dotenv

load_dotenv()  # picks up a local .env file if present, no-op otherwise

# --- Timing ---
SAMPLE_INTERVAL_S = 30      # how often every sensor is read
SYNC_INTERVAL_S = 300       # how often readings are pushed out and the local table is cleared

# --- Basins ---
# EC/pH/water level live on the shared reservoir. Everything else is per-basin.
MASTER_BASIN = "master"
BASIN_IDS = ["basin_1"]     # add one entry per physical basin as they come online

# --- Fan feedback loop (bang-bang, per basin) ---
FAN_ON_TEMP_F = 72.0
FAN_OFF_TEMP_F = 58.0

# --- I2C addresses (Atlas Scientific EZO defaults, override per wiring) ---
EZO_PH_ADDRESS = 0x63
EZO_EC_ADDRESS = 0x64

# --- SQLite ---
DB_PATH = "hydro.db"

# --- Supabase / app transmission ---
# Never hardcode these. Set them in a local .env (see .env.example) or the Pi's environment.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
# Existing remote table (predates this code) is a wide row per snapshot: id, humidity,
# temperature_c, light_intensity, ec, ph, recorded_at — no basin_id yet. Fine for pH-only now;
# will need a basin_id column (or a rethink) once other basins/sensors start syncing.
SUPABASE_READINGS_TABLE = "sensor_readings"
