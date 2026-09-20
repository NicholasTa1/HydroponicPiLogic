"""Central config for the Pi control subsystem. Tune values here, not in the modules."""

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
SUPABASE_URL = ""
SUPABASE_KEY = ""
