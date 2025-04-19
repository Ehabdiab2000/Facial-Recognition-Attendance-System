import os
import json
import logging
import cv2
logger = logging.getLogger(__name__)

# --- General ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "attendance.db")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")

# --- Default Settings (used if file is missing or key is not found) ---
DEFAULT_SETTINGS = {
    "PRIMARY_CAMERA_INDEX": 0,
    "SECONDARY_CAMERA_INDEX": 1,
    "FRAME_WIDTH": 640,
    "FRAME_HEIGHT": 480,
    "FPS_LIMIT": 10,
    "RECOGNITION_THRESHOLD": 0.55,
    "UNKNOWN_PERSON_LABEL": "Unknown",
    "RECOGNITION_COOLDOWN_SEC": 5,
    "EYE_AR_THRESH": 0.22,
    "EYE_AR_CONSEC_FRAMES": 2,
    "BLINK_DETECTION_INTERVAL_FRAMES": 5,
    "SERVER_URL": "http://your_attendance_server.com/api/log_attendance",
    "NETWORK_TIMEOUT_SEC": 10,
    "NETWORK_RETRY_DELAY_SEC": 30,
    "USE_GPIO": True,
    "RELAY_PIN": 17,
    "DOOR_OPEN_DURATION_SEC": 3,
    "GREEN_LED_PIN": 27,
    "RED_LED_PIN": 22,
    "APP_TITLE": "Facial Recognition Attendance"
}

# --- Load Settings Function ---
def load_settings():
    settings = DEFAULT_SETTINGS.copy()
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                loaded_settings = json.load(f)
                # Update settings, keeping defaults for missing keys
                for key, value in loaded_settings.items():
                    if key in settings:
                        settings[key] = value
                    else:
                        logger.warning(f"Ignoring unknown setting '{key}' from {SETTINGS_FILE}")
        else:
            logger.warning(f"{SETTINGS_FILE} not found. Using default settings.")
            # Optionally create the file with defaults
            # with open(SETTINGS_FILE, 'w') as f:
            #     json.dump(settings, f, indent=2)
    except json.JSONDecodeError:
        logger.error(f"Error decoding {SETTINGS_FILE}. Using default settings.", exc_info=True)
    except Exception:
        logger.error("Unexpected error loading settings. Using default settings.", exc_info=True)
    return settings

# --- Apply Loaded Settings ---
_loaded_config = load_settings()

# --- Camera ---
PRIMARY_CAMERA_INDEX = _loaded_config["PRIMARY_CAMERA_INDEX"]
SECONDARY_CAMERA_INDEX = _loaded_config.get("SECONDARY_CAMERA_INDEX", None) # Allow None
FRAME_WIDTH = _loaded_config["FRAME_WIDTH"]
FRAME_HEIGHT = _loaded_config["FRAME_HEIGHT"]
FPS_LIMIT = _loaded_config["FPS_LIMIT"]

# --- Recognition ---
RECOGNITION_THRESHOLD = _loaded_config["RECOGNITION_THRESHOLD"]
UNKNOWN_PERSON_LABEL = _loaded_config["UNKNOWN_PERSON_LABEL"]
RECOGNITION_COOLDOWN_SEC = _loaded_config["RECOGNITION_COOLDOWN_SEC"]

# --- Liveness (Basic Blink Detection) ---
EYE_AR_THRESH = _loaded_config["EYE_AR_THRESH"]
EYE_AR_CONSEC_FRAMES = _loaded_config["EYE_AR_CONSEC_FRAMES"]
BLINK_DETECTION_INTERVAL_FRAMES = _loaded_config["BLINK_DETECTION_INTERVAL_FRAMES"]

# --- Network ---
SERVER_URL = _loaded_config["SERVER_URL"]
NETWORK_TIMEOUT_SEC = _loaded_config["NETWORK_TIMEOUT_SEC"]
NETWORK_RETRY_DELAY_SEC = _loaded_config["NETWORK_RETRY_DELAY_SEC"]

# --- Hardware (GPIO - BCM numbering) ---
USE_GPIO = _loaded_config["USE_GPIO"]
RELAY_PIN = _loaded_config["RELAY_PIN"]
DOOR_OPEN_DURATION_SEC = _loaded_config["DOOR_OPEN_DURATION_SEC"]
GREEN_LED_PIN = _loaded_config["GREEN_LED_PIN"]
RED_LED_PIN = _loaded_config["RED_LED_PIN"]

# --- UI ---
APP_TITLE = _loaded_config["APP_TITLE"]
FONT = cv2.FONT_HERSHEY_DUPLEX
FONT_SCALE = 0.7
FONT_THICKNESS = 2

# --- Function to update a setting in memory and save to file ---
def update_setting(key, value):
    """Updates a setting in the loaded config and saves to the JSON file."""
    global _loaded_config
    if key in _loaded_config:
        _loaded_config[key] = value
        # Update the global variable if it exists (e.g., RECOGNITION_THRESHOLD)
        if key in globals():
            globals()[key] = value
        else:
             logger.warning(f"Setting '{key}' updated in memory dict, but no corresponding global variable found.")

        try:
            # Read existing settings first to preserve unknown/new ones
            current_file_settings = {}
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r') as f:
                    try:
                        current_file_settings = json.load(f)
                    except json.JSONDecodeError:
                        logger.error(f"Error reading {SETTINGS_FILE} before saving. Overwriting with current config.")
                        current_file_settings = _loaded_config # Fallback
            else:
                 current_file_settings = _loaded_config # Use current if file doesn't exist

            # Update the specific key
            current_file_settings[key] = value

            # Save the updated dictionary
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(current_file_settings, f, indent=2)
            logger.info(f"Setting '{key}' updated to '{value}' and saved to {SETTINGS_FILE}")
            return True
        except Exception:
            logger.error(f"Error saving settings to {SETTINGS_FILE}", exc_info=True)
            return False
    else:
        logger.error(f"Attempted to update unknown setting '{key}'")
        return False