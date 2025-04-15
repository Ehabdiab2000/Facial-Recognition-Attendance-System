# config.py
import os

# --- General ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "attendance.db")

# --- Camera ---
# Try to use camera 0 for primary, camera 1 for secondary/liveness check
PRIMARY_CAMERA_INDEX = 0
SECONDARY_CAMERA_INDEX = 1 # Set to None if only one camera
FRAME_WIDTH = 640  # Processing frame width
FRAME_HEIGHT = 480 # Processing frame height
FPS_LIMIT = 10     # Limit processing FPS to save resources

# --- Recognition ---
RECOGNITION_THRESHOLD = 0.55 # Lower value means stricter matching
UNKNOWN_PERSON_LABEL = "Unknown"
RECOGNITION_COOLDOWN_SEC = 5 # Seconds before recognizing the same person again

# --- Liveness (Basic Blink Detection) ---
EYE_AR_THRESH = 0.22         # Eye Aspect Ratio threshold for blink
EYE_AR_CONSEC_FRAMES = 2   # Number of consecutive frames the eye must be below threshold
BLINK_DETECTION_INTERVAL_FRAMES = 5 # Check for blinks every N frames for a detected face

# --- Network ---
SERVER_URL = "http://your_attendance_server.com/api/log_attendance" # Replace with your actual server URL
NETWORK_TIMEOUT_SEC = 10
NETWORK_RETRY_DELAY_SEC = 30

# --- Hardware (GPIO - BCM numbering) ---
USE_GPIO = True # Set to False when testing on a non-Pi machine
RELAY_PIN = 17
DOOR_OPEN_DURATION_SEC = 3
GREEN_LED_PIN = 27
RED_LED_PIN = 22

# --- UI ---
APP_TITLE = "Facial Recognition Attendance"