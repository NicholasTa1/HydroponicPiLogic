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

# --- ADC (Adafruit ADS1115) ---
# The Pi has no analog inputs, so analog probes are read through this I2C ADC.
ADS1115_ADDRESS = 0x48      # ADDR pin to GND / unconnected; 0x49-0x4B if rewired
ADS1115_PGA = 1             # +/-4.096V full scale, covers the pH board's output swing
PH_ADC_CHANNEL = 0          # A0

# --- pH probe (DFRobot SEN0161/SEN0169 analog board) ---
# pH is linear in the board's output voltage: pH = PH_SLOPE * volts + PH_INTERCEPT.
# 3.5 / 0.0 are DFRobot's defaults for an UNCALIBRATED board — readings will be plausible
# but wrong until these are replaced with what calibrate_ph.py prints.
PH_SLOPE = 3.5
PH_INTERCEPT = 0.0
PH_SAMPLES_PER_READ = 5     # median of N ADC reads; raw analog pH output is noisy

EZO_EC_ADDRESS = 0x64       # EC hardware not confirmed yet; may end up analog on the ADC too

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
