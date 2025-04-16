# settings_dialog.py
import logging
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QDoubleSpinBox,
    QPushButton, QMessageBox, QFormLayout, QGroupBox, QCheckBox
)
from PyQt6.QtCore import Qt
# Import the update_setting function and necessary config values
import config
from config import update_setting

logger = logging.getLogger(__name__)

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("System Settings")
        self.setModal(True)
        self.setMinimumWidth(500)

        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        # --- Recognition Settings ---
        recognition_group = QGroupBox("Recognition Settings")
        recognition_layout = QFormLayout()
        self.threshold_spinbox = QDoubleSpinBox()
        self.threshold_spinbox.setRange(0.1, 1.0)
        self.threshold_spinbox.setSingleStep(0.05)
        self.threshold_spinbox.setDecimals(2)
        recognition_layout.addRow("Recognition Threshold:", self.threshold_spinbox)

        self.cooldown_spinbox = QSpinBox()
        self.cooldown_spinbox.setRange(0, 60)
        self.cooldown_spinbox.setSuffix(" seconds")
        recognition_layout.addRow("Recognition Cooldown:", self.cooldown_spinbox)
        recognition_group.setLayout(recognition_layout)
        form_layout.addRow(recognition_group)

        # --- Camera Settings ---
        camera_group = QGroupBox("Camera Settings")
        camera_layout = QFormLayout()
        self.primary_cam_spinbox = QSpinBox()
        self.primary_cam_spinbox.setRange(0, 10)
        camera_layout.addRow("Primary Camera Index:", self.primary_cam_spinbox)

        # Add more settings as needed (e.g., FPS, resolution)
        camera_group.setLayout(camera_layout)
        form_layout.addRow(camera_group)

        # --- Hardware Settings ---
        hardware_group = QGroupBox("Hardware Settings (Requires Restart)")
        hardware_layout = QFormLayout()
        self.use_gpio_checkbox = QCheckBox("Enable GPIO Features")
        hardware_layout.addRow(self.use_gpio_checkbox)

        self.relay_pin_spinbox = QSpinBox()
        self.relay_pin_spinbox.setRange(0, 40)
        hardware_layout.addRow("Relay Pin (BCM):", self.relay_pin_spinbox)

        self.door_duration_spinbox = QSpinBox()
        self.door_duration_spinbox.setRange(1, 10)
        self.door_duration_spinbox.setSuffix(" seconds")
        hardware_layout.addRow("Door Open Duration:", self.door_duration_spinbox)

        self.green_led_spinbox = QSpinBox()
        self.green_led_spinbox.setRange(0, 40)
        hardware_layout.addRow("Green LED Pin (BCM):", self.green_led_spinbox)

        self.red_led_spinbox = QSpinBox()
        self.red_led_spinbox.setRange(0, 40)
        hardware_layout.addRow("Red LED Pin (BCM):", self.red_led_spinbox)

        hardware_group.setLayout(hardware_layout)
        form_layout.addRow(hardware_group)

        self.main_layout.addLayout(form_layout)

        # --- Dialog Buttons ---
        button_layout = QHBoxLayout()
        self.save_button = QPushButton("Save Settings")
        self.save_button.clicked.connect(self.save_settings)
        button_layout.addWidget(self.save_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)

        self.main_layout.addLayout(button_layout)

    def _load_settings(self):
        """Load current settings from config module."""
        try:
            # Use the dynamically loaded values from config
            self.threshold_spinbox.setValue(config.RECOGNITION_THRESHOLD)
            self.cooldown_spinbox.setValue(config.RECOGNITION_COOLDOWN_SEC)
            self.primary_cam_spinbox.setValue(config.PRIMARY_CAMERA_INDEX)
            # Load hardware settings
            self.use_gpio_checkbox.setChecked(config.USE_GPIO)
            self.relay_pin_spinbox.setValue(config.RELAY_PIN)
            self.door_duration_spinbox.setValue(config.DOOR_OPEN_DURATION_SEC)
            self.green_led_spinbox.setValue(config.GREEN_LED_PIN)
            self.red_led_spinbox.setValue(config.RED_LED_PIN)

            # Enable/disable hardware fields based on checkbox
            self._toggle_gpio_fields(config.USE_GPIO)
            self.use_gpio_checkbox.stateChanged.connect(self._toggle_gpio_fields)

        except AttributeError as e:
            logger.error(f"Error loading setting: {e}. Check config.py and settings.json.")
            QMessageBox.warning(self, "Load Error", f"Could not load setting: {e}. Check config.py and settings.json.")
        except Exception as e:
            logger.exception("Unexpected error loading settings.")
            QMessageBox.critical(self, "Load Error", "An unexpected error occurred while loading settings.")

    def _toggle_gpio_fields(self, state):
        """Enable or disable GPIO-related input fields."""
        # Handle both boolean (initial load) and Qt state (signal)
        if isinstance(state, bool):
            enabled = state
        else: # Assuming Qt.CheckState enum value
            enabled = bool(state == Qt.CheckState.Checked.value)

        self.relay_pin_spinbox.setEnabled(enabled)
        self.door_duration_spinbox.setEnabled(enabled)
        self.green_led_spinbox.setEnabled(enabled)
        self.red_led_spinbox.setEnabled(enabled)

    def save_settings(self):
        """Save settings using the update_setting function from config."""
        settings_to_save = {
            "RECOGNITION_THRESHOLD": self.threshold_spinbox.value(),
            "RECOGNITION_COOLDOWN_SEC": self.cooldown_spinbox.value(),
            "PRIMARY_CAMERA_INDEX": self.primary_cam_spinbox.value(),
            "USE_GPIO": self.use_gpio_checkbox.isChecked(),
            "RELAY_PIN": self.relay_pin_spinbox.value(),
            "DOOR_OPEN_DURATION_SEC": self.door_duration_spinbox.value(),
            "GREEN_LED_PIN": self.green_led_spinbox.value(),
            "RED_LED_PIN": self.red_led_spinbox.value(),
        }

        all_saved = True
        errors = []

        for key, value in settings_to_save.items():
            # Only save GPIO pins if USE_GPIO is checked
            if key in ["RELAY_PIN", "DOOR_OPEN_DURATION_SEC", "GREEN_LED_PIN", "RED_LED_PIN"] and not settings_to_save["USE_GPIO"]:
                continue # Skip saving these if GPIO is disabled

            if not update_setting(key, value):
                all_saved = False
                errors.append(key)

        if all_saved:
            logger.info("Settings updated and saved successfully.")
            QMessageBox.information(self, "Settings Saved",
                                    "Settings have been saved. Some changes may require an application restart.")
            self.accept() # Close dialog
        else:
            logger.error(f"Failed to save some settings: {', '.join(errors)}")
            QMessageBox.critical(self, "Save Error", f"An error occurred while saving settings for: {', '.join(errors)}. Check logs.")

# Example usage (for testing)
if __name__ == '__main__':
    import sys
    from PyQt6.QtWidgets import QApplication

    # Ensure logging is configured for testing
    logging.basicConfig(level=logging.INFO)

    # No need for MockConfig anymore, config should load from defaults/file

    app = QApplication(sys.argv)
    dialog = SettingsDialog()
    dialog.exec()