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

# --- EC probe (SenseCAP S-EC-01, analog 0-2V output) ---
EC_ADC_CHANNEL = 1          # A1

# The volts -> uS/cm multiplier depends on which output range the unit was ordered with, and
# getting it wrong scales every reading by up to 10x. Datasheet section 6:
#     0-2000 uS/cm  -> 1000      0-5000 uS/cm  -> 2500
#     0-10000 uS/cm -> 5000      0-20000 uS/cm -> 10000
# Confirm empirically: in 1413 uS/cm calibration solution the output should read
#     1.413V (1000) | 0.565V (2500) | 0.283V (5000) | 0.141V (10000)
# Those are far enough apart to be unambiguous — use read_adc.py to check.
EC_VOLTS_TO_US_CM = 1000
EC_SAMPLES_PER_READ = 5

# The sensor applies its own temperature compensation internally (2%/degC by default), which
# is what spec §4 requires — so unlike the EZO plan, nothing needs doing in software here.
# Calibration is also on-device (buttons SW2/SW3 against 1413 and 12880 uS/cm solutions),
# not a slope we fit ourselves, so there is no EC equivalent of calibrate_ph.py.

# --- SQLite ---
DB_PATH = "hydro.db"
SYNC_BATCH_LIMIT = 300      # rows per request; spec §8 caps a push at a few hundred
SQLITE_BUSY_TIMEOUT_S = 2   # wait out a brief lock instead of erroring; every process sets it

# --- Shared schema ---
# Local sensor name -> the column the app knows it by. Used by BOTH the Supabase sync and the
# BLE server, so the two paths cannot drift into reporting the same reading under different
# names. Sensors absent here have nowhere to go: `water_temp` has no column anywhere yet.
REMOTE_COLUMNS = {
    "ph": "ph",
    "ec": "ec",
    "temperature": "temperature_c",
    "humidity": "humidity",
    "light": "light_intensity",
    "co2": "co2",
}

# --- BLE ---
# Fixed UUIDs. The app hard-codes these same values; see docs/ble-protocol.md.
BLE_SERVICE_UUID = "6e3a1f80-5c21-4a7e-9d1b-2f8c4a0e7b31"
BLE_CONTROL_UUID = "6e3a1f81-5c21-4a7e-9d1b-2f8c4a0e7b31"
BLE_DATA_UUID = "6e3a1f82-5c21-4a7e-9d1b-2f8c4a0e7b31"
BLE_DEVICE_PREFIX = "HydroPi"
BLE_NOTIFY_GAP_S = 0.02     # pacing so Android's notification queue does not drop messages
BLE_MAX_ROWS = 50           # ceiling on what one GET may ask for
BLE_STALE_AFTER_S = 180     # readings older than this mean the sensor loop has stalled

# --- Supabase / app transmission ---
# Never hardcode these. Set them in a local .env (see .env.example) or the Pi's environment.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
# Existing remote table (predates this code) is a wide row per snapshot: id, humidity,
# temperature_c, light_intensity, ec, ph, recorded_at — no basin_id yet. Fine for pH-only now;
# will need a basin_id column (or a rethink) once other basins/sensors start syncing.
SUPABASE_READINGS_TABLE = "sensor_readings"
