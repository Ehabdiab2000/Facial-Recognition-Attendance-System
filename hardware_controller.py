# hardware_controller.py
import time
import config
import logging

logger = logging.getLogger(__name__)

# Mock GPIO for testing on non-Pi systems
try:
    if config.USE_GPIO:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM) # Use Broadcom pin numbering
        GPIO.setup(config.RELAY_PIN, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(config.GREEN_LED_PIN, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(config.RED_LED_PIN, GPIO.OUT, initial=GPIO.HIGH) # Default to Red LED ON
        logger.info("GPIO initialized successfully.")
        IS_PI = True
    else:
        logger.warning("GPIO usage is disabled in config. Running in mock mode.")
        IS_PI = False
        GPIO = None # Define GPIO as None if not used
except ImportError:
    logger.warning("RPi.GPIO library not found. Running in mock mode.")
    IS_PI = False
    GPIO = None
except RuntimeError as e:
    logger.error(f"Error setting up GPIO: {e}. Possibly running on non-Pi or permission issues. Running in mock mode.")
    IS_PI = False
    GPIO = None # Define GPIO as None if error during setup

def activate_relay():
    """Activates the relay for a predefined duration."""
    if IS_PI and GPIO:
        try:
            logger.info(f"Activating relay (Pin {config.RELAY_PIN}) for {config.DOOR_OPEN_DURATION_SEC} seconds.")
            GPIO.output(config.RELAY_PIN, GPIO.HIGH)
            time.sleep(config.DOOR_OPEN_DURATION_SEC)
            GPIO.output(config.RELAY_PIN, GPIO.LOW)
            logger.info(f"Deactivating relay (Pin {config.RELAY_PIN}).")
        except Exception as e:
            logger.error(f"Error controlling relay: {e}")
    else:
        logger.info(f"[MOCK] Activate relay for {config.DOOR_OPEN_DURATION_SEC} seconds.")

def set_led_status(identified: bool):
    """Sets the LED status: Green for identified, Red for not identified/default."""
    if IS_PI and GPIO:
        try:
            if identified:
                GPIO.output(config.GREEN_LED_PIN, GPIO.HIGH)
                GPIO.output(config.RED_LED_PIN, GPIO.LOW)
                logger.debug("LED set to GREEN")
            else:
                GPIO.output(config.GREEN_LED_PIN, GPIO.LOW)
                GPIO.output(config.RED_LED_PIN, GPIO.HIGH)
                logger.debug("LED set to RED")
        except Exception as e:
            logger.error(f"Error controlling LEDs: {e}")
    else:
        status = "GREEN" if identified else "RED"
        logger.info(f"[MOCK] Set LED status to {status}")

def cleanup():
    """Cleans up GPIO resources."""
    if IS_PI and GPIO:
        logger.info("Cleaning up GPIO pins.")
        GPIO.cleanup([config.RELAY_PIN, config.GREEN_LED_PIN, config.RED_LED_PIN]) # Specify pins to cleanup
    else:
        logger.info("[MOCK] GPIO cleanup.")

# Ensure initial state is Red
set_led_status(False)