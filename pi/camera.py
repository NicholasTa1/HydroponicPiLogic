import csv
import statistics
import time
from datetime import datetime
from pathlib import Path
import os
from supabase import create_client, Client
import cv2
import numpy as np
from dotenv import load_dotenv
from gpiozero import Device, InputDevice, OutputDevice
from gpiozero.pins.mock import MockFactory

if os.name == "nt":
    Device.pin_factory = MockFactory()

load_dotenv()
# ---------------- CONFIG ----------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing Supabase credentials. Check your .env file.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

CAMERA_INDEX = 0
WIDTH, HEIGHT = 1280, 720     # 720p keeps memory/CPU low on a Pi; raise if you need detail
WARMUP_FRAMES = 30            # discard frames so the sensor settles
FIXED_EXPOSURE = None         # driver-specific value, e.g. -6 on many Linux webcams; None = leave alone
ROI = None                    # (x, y, w, h) crop to just the plant tray; None = full frame
WHITE_PATCH = None            # (x, y, w, h) of a white/gray reference card in frame; None = skip

MIN_BRIGHTNESS = 40           # ignore pixels darker than this (chromaticity is noisy in shadow)
EXG_THRESHOLD = 0.05          # normalized ExG cutoff for "green"
STRESS_HUE = (10, 34)         # OpenCV hue (0-179): yellow/brown range
STRESS_MIN_SAT = 80
STRESS_MIN_VAL = 60
CM2_PER_PIXEL = 0.015         # calibrate with an object of known size at plant distance

# Anchor paths to the script folder so cron (which runs from a different cwd) still works
OUTPUT_DIR = Path(__file__).resolve().parent / "captures"
KEEP_DAYS = 30                # delete saved images older than this (protects the SD card); CSV is kept
LOG_FILE = OUTPUT_DIR / "plant_log.csv"
BASELINE_WINDOW = 5           # compare against median of the last N captures
CANOPY_DROP_LIMIT = 0.15      # flag if canopy shrinks >15% vs baseline
STRESS_RISE_LIMIT = 0.10      # flag if yellow/brown fraction rises by 0.10
EXG_DROP_LIMIT = 0.03         # flag if mean green strength drops by this much
CAMERA_INTERVAL_SEC = 15
# ----------------------------------------
SENSOR_PIN = 11               # BCM GPIO 27 wired to SEN0204 'OUT' (via 3.3V divider)
VALVE_PIN = 19                # BCM GPIO 17 wired to 24 VAC relay for NITRA valve
RELAY_ACTIVE_HIGH = False     # False for standard Active-LOW relay boards

SENSOR_DEBOUNCE_SEC = 2.0     # Confirm LOW for 2s to ignore splashes
OVERFILL_BUFFER_SEC = 5.0     # Extra fill after hitting 1 (set 0.0 for instant stop)
MAX_REFILL_TIMEOUT_SEC = 45.0 # Hard cutoff if sensor falls off the tank wall
COOLDOWN_SEC = 300.0          # Minimum 5-minute wait between refills

level_sensor = InputDevice(SENSOR_PIN, pull_up=False)
valve_relay = OutputDevice(VALVE_PIN, active_high=RELAY_ACTIVE_HIGH, initial_value=False)
last_refill_time = 0.0

def check_and_refill_water():
    """Checks SEN0204 sensor; opens NITRA valve when 0 (LOW) and stops when 1 (HIGH)."""
    global last_refill_time

    for _ in range(4):
        if level_sensor.is_active:  # 1 (HIGH) = water present
            return False, 0.0
        time.sleep(SENSOR_DEBOUNCE_SEC / 4.0)

    if (time.time() - last_refill_time) < COOLDOWN_SEC:
        return False, 0.0

    start_time = time.time()
    try:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Water LOW (0). Opening NITRA valve...")
        valve_relay.on()

        while not level_sensor.is_active:
            if (time.time() - start_time) >= MAX_REFILL_TIMEOUT_SEC:
                print("WARNING: 45s safety timeout reached before sensor read 1! Stopping valve.")
                break
            time.sleep(0.5)
        else:
            print("Sensor output 1 (Water detected)! Stopping refill...")
            if OVERFILL_BUFFER_SEC > 0:
                time.sleep(OVERFILL_BUFFER_SEC)

        duration = round(time.time() - start_time, 1)
        last_refill_time = time.time()
        return True, duration

    except Exception as e:
        print(f"Error during water refill: {e}")
        return False, round(time.time() - start_time, 1)
    finally:
        valve_relay.off()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] NITRA valve CLOSED.")

def capture_image():
    cam = cv2.VideoCapture(CAMERA_INDEX)
    # cam = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_V4L2)
    if not cam.isOpened():
        print("Error: could not open camera.")
        return None
    try:
        cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))  # lighter on USB bandwidth/CPU
        cam.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        cam.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        # Lock auto settings so lighting changes aren't "corrected" by the camera.
        cam.set(cv2.CAP_PROP_AUTO_WB, 0)
        if FIXED_EXPOSURE is not None:
            cam.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)  # 1 = manual on Linux/V4L2 (0.25 on Windows)
            cam.set(cv2.CAP_PROP_EXPOSURE, FIXED_EXPOSURE)
        for _ in range(WARMUP_FRAMES):
            cam.read()
        ok, img = cam.read()
        return img if ok else None
    except Exception as e:
        print(f"Camera capture failed: {e}")
        return None
    finally:
        cam.release()


def white_balance_from_patch(img, patch):
    """Scale channels so a known white/gray card in the frame becomes neutral."""
    x, y, w, h = patch
    mean_bgr = img[y:y + h, x:x + w].reshape(-1, 3).mean(axis=0)
    gains = mean_bgr.mean() / mean_bgr
    return np.clip(img.astype(np.float32) * gains, 0, 255).astype(np.uint8)


def clean(mask):
    kernel = np.ones((3, 3), np.uint8)
    mask = mask.astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)   # remove speckle
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)  # fill small holes


def analyze(image):
    if WHITE_PATCH:
        image = white_balance_from_patch(image, WHITE_PATCH)
    if ROI:
        x, y, w, h = ROI
        image = image[y:y + h, x:x + w]

    b, g, r = cv2.split(image.astype(np.float32))
    total = r + g + b + 1e-5
    exg = (2 * g - r - b) / total          # brightness-normalized ExG
    valid = (total / 3) > MIN_BRIGHTNESS

    hue, sat, val = cv2.split(cv2.cvtColor(image, cv2.COLOR_BGR2HSV))
    # Yellow/brown first: ExG alone also scores yellow-green leaves as "green".
    stress_raw = (
        (hue >= STRESS_HUE[0]) & (hue <= STRESS_HUE[1])
        & (sat > STRESS_MIN_SAT) & (val > STRESS_MIN_VAL) & valid
    )
    stress = clean(stress_raw)
    green = clean((exg > EXG_THRESHOLD) & valid & ~stress_raw)

    green_px = cv2.countNonZero(green)
    stress_px = cv2.countNonZero(stress)
    canopy_px = green_px + stress_px
    green_percent = round((green_px / canopy_px) * 100, 2) if canopy_px > 0 else 0.0

    metrics = {
        "green_px": green_px,
        "stress_px": stress_px,
        "canopy_cm2": round(canopy_px * CM2_PER_PIXEL, 2),
        "stress_fraction": round(stress_px / canopy_px, 4) if canopy_px else 0.0,
        "mean_exg": round(float(exg[green > 0].mean()), 4) if green_px else 0.0,
        "mean_hue": round(float(hue[green > 0].mean()), 2) if green_px else 0.0,
        "green_percent": green_percent,
    }

    # Overlay for visual verification: green = healthy, red = yellow/brown
    overlay = image.copy()
    overlay[green > 0] = (0, 255, 0)
    overlay[stress > 0] = (0, 0, 255)
    return metrics, image, overlay


def load_history():
    if not LOG_FILE.exists():
        return []
    with open(LOG_FILE, newline="") as f:
        return list(csv.DictReader(f))


def check_wilting(metrics, history):
    """Compare to this plant's own recent baseline; alert only if flagged twice in a row."""
    recent = history[-BASELINE_WINDOW:]
    if len(recent) < 3:
        return False, False  # not enough baseline yet

    def base(key):
        return statistics.median(float(r[key]) for r in recent)

    flagged = (
        metrics["canopy_cm2"] < base("canopy_cm2") * (1 - CANOPY_DROP_LIMIT)
        or metrics["stress_fraction"] > base("stress_fraction") + STRESS_RISE_LIMIT
        or metrics["mean_exg"] < base("mean_exg") - EXG_DROP_LIMIT
    )
    previous_flagged = history[-1].get("flag") == "1"
    return flagged, flagged and previous_flagged


def log(timestamp, metrics, flagged):
    OUTPUT_DIR.mkdir(exist_ok=True)
    row = {"timestamp": timestamp, **metrics, "flag": int(flagged)}
    new_file = not LOG_FILE.exists()
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def cleanup_old_images():
    cutoff = time.time() - KEEP_DAYS * 86400
    for f in OUTPUT_DIR.glob("*.jpg"):
        if f.stat().st_mtime < cutoff:
            f.unlink()


def push_to_supabase(metrics, alert):
    table_name = "sensor_readings"

    payload = {
        "recorded_at": datetime.now().isoformat(),
        "canopy_cm2": metrics["canopy_cm2"],
        "green_pixels": metrics["green_px"],
        "green_percent": metrics["green_percent"],
        "is_wilting": alert
    }
    
    try:
        response = supabase.table(table_name).insert(payload).execute()
        print("Successfully synced metrics to database.")
    except Exception as e:
        print(f"Failed to insert database row: {e}")

def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    image = capture_image()
    if image is None:
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cv2.imwrite(str(OUTPUT_DIR / f"{stamp}_raw.jpg"), image)

    metrics, processed, overlay = analyze(image)
    cv2.imwrite(str(OUTPUT_DIR / f"{stamp}_overlay.jpg"), overlay)

    flagged, alert = check_wilting(metrics, load_history())
    log(stamp, metrics, flagged)
    cleanup_old_images()

    print(metrics)
    if alert:
        print("WARNING: possible wilting (flagged on 2 consecutive captures).")
    elif flagged:
        print("Flagged this capture; will alert if it repeats.")

    push_to_supabase(metrics, alert)

if __name__ == "__main__":
    print("Starting Unified Hydroponics Controller (Press Ctrl+C to stop)...")
    last_camera_run = 0.0

    # Local Windows simulator: starts empty (0), then triggers water full (1) after 5s
    if os.name == "nt":
        import threading
        def simulate_water_rising():
            time.sleep(5)
            print("\n[SIMULATOR] Driving virtual SEN0204 pin to 1 (HIGH - Water Detected!)")
            level_sensor.pin.drive_high()

        level_sensor.pin.drive_low()
        threading.Thread(target=simulate_water_rising, daemon=True).start()

    try:
        while True:
            check_and_refill_water()

            if (time.time() - last_camera_run) >= CAMERA_INTERVAL_SEC:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Running hourly camera capture...")
                main()
                last_camera_run = time.time()

            time.sleep(10)
    except KeyboardInterrupt:
        print("\nStopping script safely. Ensuring NITRA valve is closed...")
        valve_relay.off()
