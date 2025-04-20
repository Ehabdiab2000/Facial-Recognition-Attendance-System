# main.py
import sys
import cv2
import numpy as np
import time
import logging
from datetime import datetime, timedelta
import os
# Core PyQt6 imports
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QSizePolicy, QMessageBox, QDialog, QStatusBar) # Added QStatusBar
from PyQt6.QtGui import QPixmap, QImage, QFont, QColor, QPainter
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread, QMutex, QMutexLocker, pyqtSlot
from PyQt6 import uic # <--- Import uic

# Import project modules
import config
import hardware_controller as hw
from database_manager import DatabaseManager
from network_manager import NetworkManager
from face_processor import FaceProcessor
from camera_thread import CameraThread
from user_management_dialog import UserManagementDialog
# Import the new settings dialog
from settings_dialog import SettingsDialog

class AutoCloseDialog(QDialog):
    # ... (AutoCloseDialog class remains unchanged) ...
    def __init__(self, message, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(False)

        # Set a fixed size for more professional appearance
        self.setFixedSize(400, 200)

        # Create a more professional looking layout
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)

        # Add a welcome header
        header = QLabel("WELCOME")
        header_font = QFont()
        header_font.setPointSize(18)
        header_font.setBold(True)
        header.setFont(header_font)
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet("color: #2c3e50;")
        layout.addWidget(header)

        # Add the user's name with larger font
        self.label = QLabel(message)
        name_font = QFont()
        name_font.setPointSize(24)
        name_font.setBold(True)
        self.label.setFont(name_font)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("color: #27ae60; margin: 10px;")
        layout.addWidget(self.label)

        # Add timestamp
        time_label = QLabel(datetime.now().strftime("%H:%M:%S"))
        time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        time_label.setStyleSheet("color: #7f8c8d; font-size: 14px;")
        layout.addWidget(time_label)

        # Set dialog styling
        self.setStyleSheet("""
            QDialog {
                background-color: white;
                border: 2px solid #3498db;
                border-radius: 10px;
            }
        """)

        self.setLayout(layout)
        self.show()

        # Move to center-top position
        screen_geometry = QApplication.primaryScreen().geometry()
        self.move(
            int((screen_geometry.width() - self.width()) / 2),
            50
        )

        # Add a self-closing timer
        self.close_timer = QTimer(self)
        self.close_timer.timeout.connect(self.close)
        self.close_timer.setSingleShot(True)

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, # Change to DEBUG for more detail
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# --- End Logging Setup ---


# --- Worker thread ---
class Worker(QObject):
    # Define signals that the worker can emit
    recognition_result = pyqtSignal(list, list) # Emits face locations and recognized data
    status_update = pyqtSignal(str, str)      # Emits status message and color

    def __init__(self, face_processor: FaceProcessor):
        super().__init__()
        self.face_processor = face_processor
        logger.info("Worker object initialized.")

    @pyqtSlot(object, int)
    def process_this_frame(self, frame_rgb, frame_count):
        """Processes the received frame and emits results."""
        if frame_rgb is None:
             logger.warning("Worker received None frame.")
             return

        try:
            logger.debug(f"Worker processing frame {frame_count}")
            face_locations, recognized_data = self.face_processor.process_frame(
                frame_rgb, frame_count
            )
            self.recognition_result.emit(face_locations, recognized_data)
            logger.debug(f"Worker finished frame {frame_count}")
        except Exception as e:
            logger.error(f"Error during face processing in worker: {e}", exc_info=True)
            self.status_update.emit(f"Processing Error: {e}", "red")


class MainWindow(QMainWindow):

    request_processing = pyqtSignal(object, int)
    def __init__(self):
        super().__init__()
        self.setWindowTitle(config.APP_TITLE)
        # UI is loaded below, size comes from UI file
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        # Now, make it fullscreen
        self.showFullScreen() # Optional: Keep if UI file size isn't 600x1024

        # --- Initialize Core Components ---
        self.db_manager = DatabaseManager()
        self.face_processor = FaceProcessor(self.db_manager)
        self.network_manager = NetworkManager(self.db_manager) # Starts its own thread

        # --- State Variables ---
        self.last_known_face_locations = []
        self.last_recognized_data = []
        self.last_frame_time = time.time()
        self.frame_counter = 0
        self.current_primary_frame = None # Store latest frame from primary cam
        self.last_recognition_details = {} # Store last recognition time per user ID
        self.processing_active = True # Flag to control processing
        self.recognition_paused_until = None # Timestamp until which recognition is paused
        self.welcome_dialog = None # Changed from message_box to dialog

        # --- Setup UI Elements (Loading from .ui file) ---
        self._setup_ui() # <--- Call the modified setup method

        # --- Setup Worker Thread for Processing ---
        self.worker_thread = QThread(self)
        self.worker = Worker(self.face_processor)
        self.worker.moveToThread(self.worker_thread)

        # Connect signals/slots for worker
        self.worker.recognition_result.connect(self.handle_recognition_result)
        self.worker.status_update.connect(self.update_status_label) # Connect worker status updates
        self.request_processing.connect(self.worker.process_this_frame)
        self.worker_thread.start()
        logger.info("Worker thread started.")

        # --- Setup Camera Threads ---
        self.camera_threads = {}
        self.start_camera(config.PRIMARY_CAMERA_INDEX, config.FPS_LIMIT)
        if config.SECONDARY_CAMERA_INDEX is not None:
             logger.warning("Secondary camera is configured but currently only used for potential future liveness/display.")

        # --- Periodic UI Update Timer (for FPS display, etc.) ---
        self.ui_update_timer = QTimer(self)
        self.frame_count_since_last_update = 0
        self.last_fps_update_time = time.time()

        def update_fps_status(): # Renamed function
            now = time.time()
            elapsed = now - self.last_fps_update_time
            if elapsed > 0:
                fps = self.frame_count_since_last_update / elapsed
                # Update the permanent widget in the status bar
                if hasattr(self, 'fps_status_label'): # Check if label exists
                    self.fps_status_label.setText(f"FPS: {fps:.1f}")
                self.frame_count_since_last_update = 0
                self.last_fps_update_time = now

        self.ui_update_timer.timeout.connect(update_fps_status) # Connect renamed function
        self.ui_update_timer.start(1000)

        # Initial status message
        self.update_status_label("Status: System Initializing...", "white")

    def _setup_ui(self):
        """Loads the UI from mainwindow.ui and connects signals."""
        try:
            # --- Get the absolute path to the directory containing main.py ---
            script_dir = os.path.dirname(os.path.abspath(__file__))
            # --- Construct the absolute path to the UI file ---
            ui_file_path = os.path.join(script_dir, 'mainwindow.ui')

            logger.info(f"Loading UI from {ui_file_path}") # Log the full path
            uic.loadUi(ui_file_path, self) # <--- Load using the absolute path

            # --- Connect UI Elements to Methods ---
            # Buttons from UI file (names must match objectName in Qt Designer)
            self.usermanagement.clicked.connect(self.open_user_management_dialog) # 'usermanagement' is the objectName
            self.setting.clicked.connect(self.open_settings_dialog)   # 'setting' is the objectName
            self.adduser_2.clicked.connect(self.close)                # 'adduser_2' is the Exit button's objectName

            # Connect new buttons to placeholder methods
            self.signin.clicked.connect(self.handle_signin)
            self.signout.clicked.connect(self.handle_signout)
            self.breakin.clicked.connect(self.handle_breakin) # Assuming 'breakin' is the objectName for Break In
            self.breakout_2.clicked.connect(self.handle_breakout) # Assuming 'breakout_2' is the objectName for Break Out

            # --- Setup Status Bar ---
            # The status bar is loaded from the UI file (self.statusbar)
            # Make sure it's enabled and visible if needed
            self.statusbar.setEnabled(True)
            self.statusbar.setVisible(True) # Make sure it's visible

            # Create and add the FPS label as a permanent widget to the status bar
            self.fps_status_label = QLabel("FPS: --")
            self.statusbar.addPermanentWidget(self.fps_status_label)

            # Set initial text for the video label (imgLable from UI file)
            self.imgLable.setText("Initializing Camera...")
            self.imgLable.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.imgLable.setStyleSheet("background-color: #222; color: white;") # Style similarly

            # Optional: If your mainwindow.ui doesn't force fullscreen/size
            # self.showFullScreen() # Or set a fixed size based on UI: self.setFixedSize(600, 1024)

        except FileNotFoundError:
            logger.error("mainwindow.ui not found! Cannot load UI.")
            # Handle error appropriately, maybe show a message box and exit
            QMessageBox.critical(self, "Error", "UI file 'mainwindow.ui' not found.\nApplication cannot start.")
            sys.exit(1) # Exit if UI cannot be loaded
        except Exception as e:
            logger.error(f"Error loading UI or connecting signals: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"An error occurred during UI setup:\n{e}")
            sys.exit(1)

    # --- Placeholder methods for new buttons ---
    def handle_signin(self):
        logger.info("Sign In button clicked (placeholder)")
        self.update_status_label("Action: Sign In (Not Implemented)", "yellow")
        # TODO: Implement Sign In logic

    def handle_signout(self):
        logger.info("Sign Out button clicked (placeholder)")
        self.update_status_label("Action: Sign Out (Not Implemented)", "yellow")
        # TODO: Implement Sign Out logic

    def handle_breakin(self):
        logger.info("Break In button clicked (placeholder)")
        self.update_status_label("Action: Break In (Not Implemented)", "yellow")
        # TODO: Implement Break In logic

    def handle_breakout(self):
        logger.info("Break Out button clicked (placeholder)")
        self.update_status_label("Action: Break Out (Not Implemented)", "yellow")
        # TODO: Implement Break Out logic

    def handle_users_changed(self):
        """Slot connected to the users_changed signal from UserManagementDialog."""
        logger.info("User data changed, reloading known face encodings.")
        try:
            self.face_processor.load_known_faces() # Reload faces in the processor
            self.update_status_label("Status: User data updated.", "green")
        except Exception as e:
            logger.error(f"Error reloading face encodings after user change: {e}", exc_info=True)
            self.update_status_label("Error: Failed to reload user data.", "red")

    def open_user_management_dialog(self):
        """Opens the user registration/management dialog."""
        # Ensure UserManagementDialog and its dependencies are imported
        # from user_management_dialog import UserManagementDialog # Already imported globally
        logger.info("Opening User Management dialog.")
        dialog = UserManagementDialog(self.db_manager, self.face_processor, self)
        # Connect the signal to a slot if needed (e.g., to refresh UI elements)
        dialog.users_changed.connect(self.handle_users_changed)
        dialog.exec()

    def open_settings_dialog(self):
        """Opens the system settings dialog."""
        # Pause processing while settings are open
        logger.info("Opening settings dialog.")
        self.processing_active = False
        self.stop_all_cameras()
        dialog = SettingsDialog(self) # Pass parent
        dialog.exec() # Show modally
        # Reload config or notify components if needed after save
        logger.info("Settings dialog closed. Resuming operations.")
        self.processing_active = True
        # Short delay before restarting camera
        QTimer.singleShot(500, lambda: self.start_camera(config.PRIMARY_CAMERA_INDEX, config.FPS_LIMIT))
        # Potentially re-apply some settings immediately if needed


    def start_camera(self, index, fps):
        if index in self.camera_threads and self.camera_threads[index].isRunning():
             logger.warning(f"Camera {index} thread is already running.")
             return

        thread = CameraThread(index, target_fps=fps)
        thread.frame_ready.connect(self.handle_frame)
        thread.error.connect(self.handle_camera_error)
        thread.finished.connect(lambda idx=index: self.on_camera_thread_finished(idx)) # Handle cleanup
        thread.start()
        self.camera_threads[index] = thread
        logger.info(f"Camera thread for index {index} started.")

    def show_temporary_message(self, title, text, duration_ms=3000):
        """Displays a professional-looking non-blocking welcome dialog that closes automatically."""
        # Cleanup any existing message components
        if hasattr(self, 'welcome_dialog'):
            if self.welcome_dialog:
                if hasattr(self.welcome_dialog, 'close_timer') and self.welcome_dialog.close_timer.isActive():
                    self.welcome_dialog.close_timer.stop()
                self.welcome_dialog.close()
                self.welcome_dialog.deleteLater()
            self.welcome_dialog = None

        # Create new welcome dialog with enhanced styling
        self.welcome_dialog = AutoCloseDialog(text, self)
        self.welcome_dialog.setWindowTitle(title)

        # Position the dialog at the center-top of the screen
        screen_geometry = QApplication.primaryScreen().geometry()
        dialog_size = self.welcome_dialog.size()
        self.welcome_dialog.move(
            int((screen_geometry.width() - dialog_size.width()) / 2),
            50
        )

        # Start the dialog's self-closing timer
        self.welcome_dialog.close_timer.start(duration_ms)

        logger.info(f"Showing professional welcome message for user: '{text}' for {duration_ms}ms")

    def close_welcome_message(self):
        """Safely closes the welcome dialog."""
        if hasattr(self, 'welcome_dialog') and self.welcome_dialog:
            logger.info("Closing welcome dialog.")
            if hasattr(self.welcome_dialog, 'close_timer') and self.welcome_dialog.close_timer.isActive():
                self.welcome_dialog.close_timer.stop()
            self.welcome_dialog.close()
            self.welcome_dialog = None # Clear reference
        else:
            logger.debug("close_welcome_message called but welcome dialog was already None.")


    def stop_all_cameras(self):
        logger.info("Stopping all camera threads...")
        threads_to_wait_for = []
        for index, thread in list(self.camera_threads.items()): # Use list copy for safe iteration
            if thread and thread.isRunning():
                logger.info(f"Requesting stop for camera {index}...")
                thread.stop() # stop() should ideally signal thread to finish
                threads_to_wait_for.append(thread)
            # Don't delete from dict here, wait for finished signal
        # Wait for threads to finish (optional, but good practice)
        # for thread in threads_to_wait_for:
        #     thread.wait(500) # Wait max 500ms per thread


    def on_camera_thread_finished(self, index):
         logger.info(f"Camera thread {index} has finished.")
         if index in self.camera_threads:
              # Ensure thread object cleanup if needed
              # self.camera_threads[index].deleteLater() # Example if it's a QObject
              del self.camera_threads[index] # Remove from active threads


    def handle_frame(self, frame, cam_index):
        """Handles incoming frames from camera threads."""
        if cam_index == config.PRIMARY_CAMERA_INDEX:
            self.current_primary_frame = frame # Keep latest frame
            now = time.time()
            self.frame_count_since_last_update += 1 # Increment frame counter for FPS calc

            # Check if recognition is paused
            if self.recognition_paused_until and now < self.recognition_paused_until:
                self.update_video_display(frame, [], [], paused=True)
                return # Skip processing

            elif self.recognition_paused_until and now >= self.recognition_paused_until:
                self.recognition_paused_until = None
                self.last_known_face_locations = []
                self.last_recognized_data = []
                logger.info("Recognition pause finished.")

            # Throttle processing based on FPS limit
            if self.processing_active and (now - self.last_frame_time >= 1.0 / config.FPS_LIMIT):
                self.last_frame_time = now
                self.frame_counter += 1
                logger.debug(f"Requesting processing for frame {self.frame_counter}")
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                self.request_processing.emit(frame_rgb, self.frame_counter)

            # Always update the display with the latest frame and last known results
            # Do not update if paused to prevent showing stale boxes briefly after pause ends
            if not self.recognition_paused_until:
                 self.update_video_display(frame, self.last_known_face_locations, self.last_recognized_data)
            else:
                 # Still paused, ensure display shows clean frame
                 self.update_video_display(frame, [], [], paused=True)

    @pyqtSlot(str, int)
    def handle_camera_error(self, error_msg, cam_index):
        logger.error(f"Camera {cam_index} Error: {error_msg}")
        self.update_status_label(f"Camera {cam_index} Error: {error_msg}", "red")
        if cam_index in self.camera_threads:
             # Optionally try restarting
             # del self.camera_threads[cam_index] # Remove faulty thread
             # QTimer.singleShot(5000, lambda: self.start_camera(cam_index, config.FPS_LIMIT))
             pass


    @pyqtSlot(list, list)
    def handle_recognition_result(self, face_locations, recognized_data):
        """Handles the results from the worker thread."""
        logger.debug(f"Received recognition result: {len(face_locations)} faces, {len(recognized_data)} recognized.")

        # Don't process results if paused
        if self.recognition_paused_until and time.time() < self.recognition_paused_until:
             logger.debug("Ignoring recognition result as recognition is paused.")
             # Ensure display remains clear during pause if a frame comes through
             if self.current_primary_frame is not None:
                 self.update_video_display(self.current_primary_frame, [], [], paused=True)
             return
        elif self.recognition_paused_until and time.time() >= self.recognition_paused_until:
             # Pause just ended, reset state for next frame
             self.recognition_paused_until = None
             self.last_known_face_locations = []
             self.last_recognized_data = []
             logger.info("Recognition pause finished.")
             # Don't process this specific result packet that arrived *during* the pause
             return

        # Only update last known results if not paused
        self.last_known_face_locations = face_locations
        self.last_recognized_data = recognized_data

        now = datetime.now()
        status_text = "Status: Monitoring..."
        status_color = "white"

        found_known_person = False
        processed_recognition_this_cycle = False # Flag to ensure we only process one success action

        for i, data in enumerate(recognized_data):
            user_id = data.get('id')
            name = data.get('name', config.UNKNOWN_PERSON_LABEL)
            distance = data.get('distance', 1.0)

            if user_id is not None and name != config.UNKNOWN_PERSON_LABEL:
                found_known_person = True
                if processed_recognition_this_cycle: # Skip if we already welcomed someone
                    continue

                last_seen = self.last_recognition_details.get(user_id)

                # Check cooldown
                if last_seen is None or (now - last_seen) > timedelta(seconds=config.RECOGNITION_COOLDOWN_SEC):
                    status_text = f"Welcome, {name}! (Dist: {distance:.2f})"
                    status_color = "lime"
                    logger.info(f"Recognized {name} (ID: {user_id}). Logging attendance.")
                    self.last_recognition_details[user_id] = now # Update cooldown timestamp FIRST
                    processed_recognition_this_cycle = True # Mark as processed

                    # --- Trigger Actions --- #
                    transaction_id = self.db_manager.add_transaction(user_id)
                    if transaction_id:
                        self.network_manager.queue_transaction(transaction_id)
                    else:
                        logger.error(f"Failed to log transaction for user {user_id} in the database.")
                        self.update_status_label(f"DB Error logging {name}", "red")

                    hw.activate_relay()
                    hw.set_led_status(True)
                    QTimer.singleShot(config.DOOR_OPEN_DURATION_SEC * 1000, lambda: hw.set_led_status(False))
                    self.show_temporary_message("Welcome!", f"Hello, {name}!", duration_ms=3000)

                    # --- Start Pause --- #
                    pause_duration = 4.0 # Keep the 4-second general pause
                    self.recognition_paused_until = time.time() + pause_duration
                    logger.info(f"Recognition paused for {pause_duration} seconds.")

                    # --- Immediately clear results and update display to paused state --- #
                    self.last_known_face_locations = []
                    self.last_recognized_data = []
                    if self.current_primary_frame is not None:
                         # Update display immediately to show no boxes and indicate pause
                         self.update_video_display(self.current_primary_frame, [], [], paused=True)
                    self.update_status_label(status_text, status_color) # Show the welcome message briefly

                    # Break inner loop after successful recognition and pause initiation
                    break

                else:
                    # Recognized but within cooldown
                    if not processed_recognition_this_cycle: # Show cooldown only if no one was welcomed yet
                        status_text = f"Recognized: {name} (Cooldown)"
                        status_color = "yellow"
                    logger.debug(f"Recognized {name} (ID: {user_id}) within cooldown period.")

            elif name == config.UNKNOWN_PERSON_LABEL:
                 # Only update status if no known faces were processed this cycle
                 if not found_known_person and not processed_recognition_this_cycle:
                    status_text = f"Unknown Person Detected (Closest Dist: {distance:.2f})"
                    status_color = "orange"
                    hw.set_led_status(False) # Red ON for unknown

        # --- Post-Loop Status Update --- #
        # Update status only if no recognition action was processed (welcome/pause didn't happen)
        if not processed_recognition_this_cycle:
            if not face_locations:
                # No faces detected at all in this frame
                status_text = "Status: Monitoring... No faces detected."
                status_color = "white"
                hw.set_led_status(False) # Ensure default state (Red ON) if no faces
                # Clear last results if no faces are detected currently
                self.last_known_face_locations = []
                self.last_recognized_data = []
            elif not found_known_person:
                # Faces detected, but all were unknown or in cooldown (and status wasn't set above)
                if status_text == "Status: Monitoring...": # Avoid overwriting Unknown/Cooldown status
                    status_text = "Status: Monitoring... Face(s) detected."
                    status_color = "white"
                    hw.set_led_status(False) # Red ON if only unknown/cooldown faces
            # If found_known_person is True but processed_recognition_this_cycle is False,
            # it means all known persons were in cooldown. The status (Cooldown) was likely set inside the loop.

            self.update_status_label(status_text, status_color)

        # Display update is handled by handle_frame() using the latest self.last_known_face_locations/data,
        # unless paused, in which case handle_frame() or this function forces a paused display.

    def update_video_display(self, frame, face_locations, recognized_data, paused=False):
        """Updates the video label (imgLable) with the frame and drawn boxes/names."""
        if not hasattr(self, 'imgLable'): # Check if UI element exists
            logger.warning("imgLable not found, cannot update video display.")
            return
        try:
            display_frame = frame.copy()
            h, w, _ = display_frame.shape

            if not paused:
                for i, ((top, right, bottom, left), data) in enumerate(zip(face_locations, recognized_data)):
                    name = data.get('name', config.UNKNOWN_PERSON_LABEL)
                    box_color = (0, 0, 255) # Red BGR
                    if name != config.UNKNOWN_PERSON_LABEL:
                        box_color = (0, 255, 0) # Green BGR
                    cv2.rectangle(display_frame, (left, top), (right, bottom), box_color, 2)

            # Convert frame to QPixmap
            # Check frame dimensions - resizing might be needed for the UI label size
            label_w = self.imgLable.width()
            label_h = self.imgLable.height()

            # Maintain aspect ratio while resizing
            frame_h, frame_w = display_frame.shape[:2]
            aspect_ratio = frame_w / frame_h
            target_w = label_w
            target_h = int(target_w / aspect_ratio)
            if target_h > label_h:
                target_h = label_h
                target_w = int(target_h * aspect_ratio)

            # Resize only if necessary
            if target_w != frame_w or target_h != frame_h:
                 resized_frame = cv2.resize(display_frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
            else:
                 resized_frame = display_frame

            # Convert final frame to QImage
            final_h, final_w = resized_frame.shape[:2]
            rgb_image = cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB)
            qt_image = QImage(rgb_image.data, final_w, final_h, final_w * 3, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qt_image)

            # Set pixmap, ensuring it's centered if smaller than label
            self.imgLable.setPixmap(pixmap)
            # self.imgLable.setScaledContents(False) # Let alignment handle positioning
            self.imgLable.setAlignment(Qt.AlignmentFlag.AlignCenter)


        except Exception as e:
            logger.error(f"Error updating video display: {e}", exc_info=True)
            self.imgLable.setText(f"Display Error: {e}")


    @pyqtSlot(str, str)
    def update_status_label(self, text, color="white"):
        """Updates the status bar message."""
        if hasattr(self, 'statusbar'):
            # QStatusBar doesn't directly support color in showMessage easily.
            # We can prepend info or just show the text.
            # For simplicity, just show the text. Add color logic later if needed.
            self.statusbar.showMessage(text, 0) # timeout=0 means permanent until next message
            # You could potentially set a stylesheet on the statusbar temporarily,
            # but it might look inconsistent.
            # self.statusbar.setStyleSheet(f"QStatusBar {{ color: {color}; }}")
            # logger.debug(f"Status Updated: {text}") # Log status updates
        else:
             logger.warning("Status bar not found, cannot update status.")


    def on_user_registered(self):
        """Callback when registration is successful."""
        logger.info("User registration successful signal received.")
        self.update_status_label("New user registered.", "blue")


    def on_registration_dialog_closed(self):
        """Callback when the registration dialog is closed."""
        logger.info("Registration dialog closed. Resuming operations.")
        # Short delay before restarting camera to ensure resources are free
        QTimer.singleShot(500, self.restart_main_operations)


    def restart_main_operations(self):
        """Restarts cameras and processing after registration closes."""
        self.start_camera(config.PRIMARY_CAMERA_INDEX, config.FPS_LIMIT)
        if config.SECONDARY_CAMERA_INDEX is not None:
            pass
        self.processing_active = True
        logger.info("Main camera(s) restarted and processing resumed.")


    def closeEvent(self, event):
        """Ensure cleanup on application close."""
        logger.info("MainWindow closeEvent triggered. Cleaning up...")
        self.processing_active = False
        self.stop_all_cameras()
        if hasattr(self, 'ui_update_timer') and self.ui_update_timer.isActive():
            self.ui_update_timer.stop()
            logger.debug("UI Update Timer stopped.")
        if hasattr(self, 'worker_thread') and self.worker_thread.isRunning():
            logger.debug("Stopping worker thread...")
            self.worker_thread.quit() # Ask thread's event loop to exit
            if not self.worker_thread.wait(2000): # Wait up to 2 seconds
                 logger.warning("Worker thread did not finish quitting gracefully. Forcing termination.")
                 self.worker_thread.terminate() # Force if necessary
                 self.worker_thread.wait() # Wait after terminate
            logger.debug("Worker thread stopped.")
        if hasattr(self, 'network_manager') and hasattr(self.network_manager, 'stop'):
             logger.debug("Stopping network manager...")
             self.network_manager.stop() # Assumes network_manager has a stop method that joins its thread
             logger.debug("Network manager stopped.")
        if hasattr(self, 'welcome_dialog') and self.welcome_dialog:
            self.welcome_dialog.close()
            logger.debug("Welcome dialog closed.")

        # Ensure all camera threads are really finished (belt and suspenders)
        # for index, thread in list(self.camera_threads.items()):
        #     if thread.isRunning():
        #         thread.wait(500) # Give final chance to stop
        #         if thread.isRunning():
        #             logger.warning(f"Camera thread {index} did not stop, terminating.")
        #             thread.terminate()

        logger.info("Cleanup complete. Exiting application.")
        # QApplication.quit() # This can sometimes cause issues if called directly in closeEvent
        event.accept() # Accept the close event


# --- Main Execution ---
if __name__ == "__main__":
    # Configure logging BEFORE creating QApplication for early logs if needed
    # logging.basicConfig(...) # Already done above

    app = QApplication(sys.argv)
    # Apply a style maybe?
    # app.setStyle('Fusion')

    main_window = MainWindow()
    main_window.show() # Show the window loaded from the UI file

    exit_code = app.exec()
    logger.info(f"Application exiting with code {exit_code}")
    sys.exit(exit_code) # Ensure exit code is propagated