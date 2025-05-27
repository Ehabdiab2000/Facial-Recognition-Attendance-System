# wiegand_reader.py
import time
import logging
from threading import Thread, Event
from PyQt6.QtCore import QObject, pyqtSignal # To signal card scans to main thread

logger = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
    IS_PI = True
except ImportError:
    logger.warning("RPi.GPIO not found. Wiegand reader will be mocked.")
    IS_PI = False
    GPIO = None # Mock GPIO

# --- Wiegand Reader Configuration ---
# These are EXAMPLE pins, change them to the actual GPIO pins you connect D0 and D1 to
# Use BCM numbering
PIN_D0 = 14 # Example: GPIO14
PIN_D1 = 15 # Example: GPIO15
WIEGAND_TIMEOUT_MS = 100 # Milliseconds to wait for the next bit

class WiegandReader(QObject): # Inherit QObject for signals
    card_scanned = pyqtSignal(str) # Emits the decoded card number

    def __init__(self, pin_d0=PIN_D0, pin_d1=PIN_D1, parent=None):
        super().__init__(parent)
        self.pin_d0 = pin_d0
        self.pin_d1 = pin_d1
        self._bits = []
        self._last_bit_time = 0
        self._running = False
        self._thread = None
        self._stop_event = Event()

        if IS_PI and GPIO:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.pin_d0, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(self.pin_d1, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            logger.info(f"Wiegand reader GPIO pins D0:{self.pin_d0}, D1:{self.pin_d1} initialized.")
        elif not IS_PI:
            logger.info("Wiegand reader running in mock mode.")


    def _bit_received_d0(self, channel):
        if self._running:
            self._bits.append(0)
            self._last_bit_time = time.time() * 1000 # milliseconds

    def _bit_received_d1(self, channel):
        if self._running:
            self._bits.append(1)
            self._last_bit_time = time.time() * 1000 # milliseconds

    def _process_bits(self):
        card_number_str = ""
        num_bits = len(self._bits)

        if num_bits == 0:
            return

        logger.debug(f"Processing {num_bits} Wiegand bits: {self._bits}")

        # Common Wiegand formats are 26-bit, 34-bit, 37-bit, etc.
        # Basic 26-bit format:
        # Parity Bit | Facility Code (8 bits) | Card Number (16 bits) | Parity Bit
        if num_bits == 26:
            # Example: Extract card number portion (bits 9-24, or 1 to 16 after facility code)
            # For simplicity, we'll just take the middle 16 bits as card number here
            # A more robust implementation would check parity bits and potentially facility code.
            facility_code = int("".join(map(str, self._bits[1:9])), 2)
            card_code = int("".join(map(str, self._bits[9:25])), 2) # 16 bits
            card_number_str = str(card_code)
            logger.info(f"Decoded 26-bit Wiegand: Facility={facility_code}, Card={card_code}")
        # Add other format decodings if needed (e.g., 34-bit)
        elif num_bits == 34: # Example for 34-bit
            # Often the full 32 bits between parity bits are considered the card number
            card_code = int("".join(map(str, self._bits[1:33])), 2)
            card_number_str = str(card_code)
            logger.info(f"Decoded 34-bit Wiegand: Card={card_code}")
        else:
            # For unknown formats, just join all bits as a raw binary string or hex
            card_number_str = "RAW_BINARY:" + "".join(map(str, self._bits))
            logger.warning(f"Unsupported Wiegand bit length: {num_bits}. Raw: {card_number_str}")


        if card_number_str and not card_number_str.startswith("RAW_BINARY:"):
            logger.info(f"Card scanned: {card_number_str}")
            self.card_scanned.emit(card_number_str) # Emit the signal
        elif card_number_str.startswith("RAW_BINARY:"):
            # Optionally emit raw data too if you want to handle it
            # self.card_scanned.emit(card_number_str)
            pass

        self._bits = [] # Reset for next scan

    def _reader_loop(self):
        if IS_PI and GPIO:
            GPIO.add_event_detect(self.pin_d0, GPIO.FALLING, callback=self._bit_received_d0, bouncetime=5) # bouncetime in ms
            GPIO.add_event_detect(self.pin_d1, GPIO.FALLING, callback=self._bit_received_d1, bouncetime=5)

        self._last_bit_time = time.time() * 1000

        while not self._stop_event.is_set():
            current_time = time.time() * 1000
            if len(self._bits) > 0 and (current_time - self._last_bit_time > WIEGAND_TIMEOUT_MS):
                self._process_bits()
            time.sleep(0.01) # Sleep briefly to reduce CPU usage

        logger.info("Wiegand reader loop stopped.")
        if IS_PI and GPIO:
            GPIO.remove_event_detect(self.pin_d0)
            GPIO.remove_event_detect(self.pin_d1)


    def start(self):
        if self._running:
            logger.warning("Wiegand reader already running.")
            return

        self._running = True
        self._stop_event.clear()
        self._thread = Thread(target=self._reader_loop, daemon=True)
        self._thread.start()
        logger.info("Wiegand reader thread started.")

    def stop(self):
        if not self._running:
            logger.info("Wiegand reader not running.")
            return

        logger.info("Stopping Wiegand reader thread...")
        self._running = False # Signal to callbacks to stop appending bits
        self._stop_event.set() # Signal thread to exit loop
        if self.pin_d0 is not None and IS_PI: # Trigger dummy events to break out of potential GPIO waits
            pass # This part is tricky with GPIO event detection directly
        if self._thread:
            self._thread.join(timeout=1.0) # Wait for thread to finish
            if self._thread.is_alive():
                logger.warning("Wiegand reader thread did not stop cleanly.")
        self._thread = None
        logger.info("Wiegand reader stopped.")

    # Mock function for testing on non-Pi
    def mock_scan(self, card_number):
        if not IS_PI:
            logger.info(f"[MOCK] Wiegand card scanned: {card_number}")
            self.card_scanned.emit(str(card_number))
        else:
            logger.warning("Mock scan called on Pi. Use actual reader.")

# --- Cleanup GPIO on exit ---
def cleanup_gpio():
    if IS_PI and GPIO:
        logger.info("Cleaning up Wiegand GPIO.")
        GPIO.cleanup([PIN_D0, PIN_D1]) # Clean up specific pins

if __name__ == '__main__':
    # Example usage and test
    logging.basicConfig(level=logging.DEBUG)
    reader = WiegandReader()

    def print_card(card_num):
        print(f"MAIN THREAD: Card Scanned: {card_num}")

    reader.card_scanned.connect(print_card)
    reader.start()

    print("Wiegand reader started. Try scanning a card (or use mock_scan if not on Pi).")
    try:
        if not IS_PI:
            # Simulate some scans for testing
            time.sleep(2)
            reader.mock_scan("12345")
            time.sleep(2)
            reader.mock_scan("67890")
            time.sleep(5) # Keep running for a bit
        else:
            while True:
                time.sleep(1) # Keep main thread alive while reader runs
    except KeyboardInterrupt:
        print("Exiting...")
    finally:
        reader.stop()
        cleanup_gpio()
        print("Reader stopped and GPIO cleaned up.")