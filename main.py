# main.py
import sys
import cv2
import numpy as np
import time
import logging
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                            QHBoxLayout, QLabel, QPushButton, QSizePolicy, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QMessageBox)
from PyQt6.QtGui import QPixmap, QImage, QFont, QColor, QPainter
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread, QMutex, QMutexLocker , pyqtSlot

# Import project modules
import config
import hardware_controller as hw
from database_manager import DatabaseManager
from network_manager import NetworkManager
from face_processor import FaceProcessor
from camera_thread import CameraThread
from registration_dialog import RegistrationDialog
# Import the new settings dialog
from settings_dialog import SettingsDialog

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, # Change to DEBUG for more detail
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# --- End Logging Setup ---


# --- Worker thread for blocking tasks like recognition and relay ---
class Worker(QObject):
    finished = pyqtSignal()
    # MODIFIED: Remove the bool for is_live
    recognition_result = pyqtSignal(list, list) # face_locations, recognized_data
    status_update = pyqtSignal(str, str)

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
            # MODIFIED: process_frame now returns only two values
            face_locations, recognized_data = self.face_processor.process_frame(
                frame_rgb, frame_count # Pass frame_count if needed by process_frame, otherwise remove
            )
            # MODIFIED: Emit only the two results
            self.recognition_result.emit(face_locations, recognized_data)
            logger.debug(f"Worker finished frame {frame_count}")
        except Exception as e:
            logger.error(f"Error during face processing in worker: {e}", exc_info=True)
            self.status_update.emit(f"Processing Error: {e}", "red")


    # Remove the run(self) method entirely. The QThread's event loop will handle calling the slot.
    # def run(self): ... DELETE THIS METHOD ...

    # Remove the stop(self) method, it's not needed for this slot-based approach
    # def stop(self): ... DELETE THIS METHOD ...



class MainWindow(QMainWindow):

    # We need a way to trigger the worker's run method
        # Let's use a signal from the main thread when a frame is ready to be processed
    request_processing = pyqtSignal(object, int)
    def __init__(self):
        super().__init__()
        self.setWindowTitle(config.APP_TITLE)
        # self.setGeometry(100, 100, 1024, 768) # Adjust size as needed
        self.showFullScreen() # Typically kiosk mode for RPi

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
        self.welcome_message_box = None # To hold the temporary message box

        # --- Setup UI Elements ---
        self._setup_ui()

        # --- Setup Worker Thread for Processing ---
        self.worker_thread = QThread(self)
        self.worker = Worker(self.face_processor) # Worker object created
        self.worker.moveToThread(self.worker_thread) # Worker moved to thread


        # Connect signals/slots for worker
        # These connections emit signals FROM the worker TO the main thread (MainWindow)
        self.worker.recognition_result.connect(self.handle_recognition_result)
        self.worker.status_update.connect(self.update_status_label)
        # This connection emits signals FROM the main thread TO the worker's slot
        self.request_processing.connect(self.worker.process_this_frame)
        self.worker_thread.start() # Start the thread's event loop
        logger.info("Worker thread started.")

        # --- Setup Camera Threads ---
        self.camera_threads = {}
        self.start_camera(config.PRIMARY_CAMERA_INDEX, config.FPS_LIMIT)
        if config.SECONDARY_CAMERA_INDEX is not None:
             logger.warning("Secondary camera is configured but currently only used for potential future liveness/display.")
             # self.start_camera(config.SECONDARY_CAMERA_INDEX, config.FPS_LIMIT / 2) # Run secondary slower?


        # --- Periodic UI Update Timer (for FPS display, etc.) ---
        self.ui_update_timer = QTimer(self)
        self.ui_update_timer.timeout.connect(self.update_ui_elements)
        self.ui_update_timer.start(1000) # Update FPS once per second

    def open_registration_dialog(self):
        """Pauses processing and opens the registration dialog."""
        logger.info("Opening registration dialog.")
        self.processing_active = False # Pause processing
        self.stop_all_cameras() # Stop main cameras before opening dialog's camera

        # Ensure RegistrationDialog and its dependencies are imported
        from registration_dialog import RegistrationDialog # Moved import here

        dialog = RegistrationDialog(self.db_manager, self.face_processor, self)
        dialog.user_registered.connect(self.on_user_registered) # Connect signal
        dialog.finished.connect(self.on_registration_dialog_closed) # Signal for when dialog closes
        dialog.exec() # Show dialog modally

    def _setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        # Video Display Area
        self.video_label = QLabel("Initializing Camera...")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video_label.setStyleSheet("background-color: #222;")
        self.main_layout.addWidget(self.video_label, stretch=5) # Give more space to video

        # Status/Info Area
        info_layout = QHBoxLayout()
        self.status_label = QLabel("Status: System Initializing...")
        font = self.status_label.font()
        font.setPointSize(16)
        self.status_label.setFont(font)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(self.status_label, stretch=3)

        self.fps_label = QLabel("FPS: --")
        self.fps_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        info_layout.addWidget(self.fps_label, stretch=1)

        self.main_layout.addLayout(info_layout, stretch=1)

        # Control Buttons Area
        button_layout = QHBoxLayout()
        self.register_button = QPushButton("Register New User")
        self.register_button.clicked.connect(self.open_registration_dialog)
        button_layout.addWidget(self.register_button)

        self.settings_button = QPushButton("Settings") # Add settings button
        self.settings_button.clicked.connect(self.open_settings_dialog)
        button_layout.addWidget(self.settings_button)

        # Add more buttons if needed (e.g., Settings, Shutdown)
        self.quit_button = QPushButton("Quit")
        self.quit_button.clicked.connect(self.close)
        button_layout.addWidget(self.quit_button)

        self.main_layout.addLayout(button_layout, stretch=1)

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
        """Displays a non-blocking message box that closes automatically."""
        if self.welcome_message_box and self.welcome_message_box.isVisible():
            self.welcome_message_box.close() # Close previous one if still open

        self.welcome_message_box = QMessageBox(self)
        self.welcome_message_box.setIcon(QMessageBox.Icon.Information)
        self.welcome_message_box.setWindowTitle(title)
        self.welcome_message_box.setText(text)
        self.welcome_message_box.setStandardButtons(QMessageBox.StandardButton.NoButton) # No buttons
        self.welcome_message_box.setModal(False) # Non-blocking
        # Position it somewhere reasonable, e.g., top center
        screen_geometry = QApplication.primaryScreen().geometry()
        msg_box_size = self.welcome_message_box.sizeHint()
        self.welcome_message_box.move(int((screen_geometry.width() - msg_box_size.width()) / 2), 50)
        self.welcome_message_box.show()
        QTimer.singleShot(duration_ms, self.welcome_message_box.close) # Auto-close

    def open_settings_dialog(self):
        """Opens the system settings dialog."""
        # Pause processing while settings are open?
        # self.processing_active = False # Consider implications
        dialog = SettingsDialog(self) # Pass parent
        dialog.exec() # Show modally
        # Reload config or notify components if needed after save
        # self.processing_active = True
        logger.info("Settings dialog closed.")
        # Potentially re-apply some settings immediately if needed
        # e.g., self.face_processor.load_known_faces() if threshold changed?

    def stop_all_cameras(self):
        logger.info("Stopping all camera threads...")
        for index, thread in self.camera_threads.items():
            if thread and thread.isRunning():
                logger.info(f"Stopping camera {index}...")
                thread.stop() # stop() handles waiting
        # Wait for threads to finish? Usually handled by stop() or closeEvent
        # self.camera_threads.clear() # Clear after they confirm finished


    def on_camera_thread_finished(self, index):
         logger.info(f"Camera thread {index} has finished.")
         if index in self.camera_threads:
              del self.camera_threads[index] # Remove from active threads


    def handle_frame(self, frame, cam_index):
        """Handles incoming frames from camera threads."""
        if cam_index == config.PRIMARY_CAMERA_INDEX:
            self.current_primary_frame = frame # Keep latest frame
            now = time.time()

            # Check if recognition is paused
            if self.recognition_paused_until and now < self.recognition_paused_until:
                # Still paused, update display but don't process
                self.update_video_display(frame, self.last_known_face_locations, self.last_recognized_data, paused=True)
                return # Skip processing
            else:
                # Pause finished or wasn't active
                self.recognition_paused_until = None

            # Throttle processing based on FPS limit
            if self.processing_active and (now - self.last_frame_time >= 1.0 / config.FPS_LIMIT):
                self.last_frame_time = now
                self.frame_counter += 1
                logger.debug(f"Requesting processing for frame {self.frame_counter}")
                # Convert frame to RGB for face_recognition library
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                # Emit signal to worker thread
                self.request_processing.emit(frame_rgb, self.frame_counter)

            # Always update the display with the latest frame and last known results
            self.update_video_display(frame, self.last_known_face_locations, self.last_recognized_data)

        # Handle secondary camera frame if needed (e.g., display in a corner)
        # elif cam_index == config.SECONDARY_CAMERA_INDEX:
        #     pass

    @pyqtSlot(str, int) # Decorator ensures it runs in the main thread
    def handle_camera_error(self, error_msg, cam_index):
        logger.error(f"Camera {cam_index} Error: {error_msg}")
        self.update_status_label(f"Camera {cam_index} Error: {error_msg}", "red")
        # Optionally try to restart the camera thread after a delay
        if cam_index in self.camera_threads:
            del self.camera_threads[cam_index] # Remove faulty thread
        # QTimer.singleShot(5000, lambda: self.start_camera(cam_index, config.FPS_LIMIT)) # Retry after 5s


    # MODIFIED: Update signature - remove is_live parameter
    @pyqtSlot(list, list) # Decorator ensures it runs in the main thread
    def handle_recognition_result(self, face_locations, recognized_data):
        """Handles the results from the worker thread."""
        logger.debug(f"Received recognition result: {len(face_locations)} faces, {len(recognized_data)} recognized.")
        self.last_known_face_locations = face_locations
        self.last_recognized_data = recognized_data

        now = datetime.now()
        status_text = "Status: Monitoring..."
        status_color = "white"

        found_known_person = False
        for i, data in enumerate(recognized_data):
            user_id = data.get('id')
            name = data.get('name', config.UNKNOWN_PERSON_LABEL)
            distance = data.get('distance', 1.0)

            if user_id is not None and name != config.UNKNOWN_PERSON_LABEL:
                found_known_person = True
                last_seen = self.last_recognition_details.get(user_id)

                # Check cooldown
                if last_seen is None or (now - last_seen) > timedelta(seconds=config.RECOGNITION_COOLDOWN_SEC):
                    status_text = f"Welcome, {name}! (Dist: {distance:.2f})"
                    status_color = "lime"
                    logger.info(f"Recognized {name} (ID: {user_id}). Logging attendance.")
                    self.last_recognition_details[user_id] = now

                    # --- Trigger Actions --- #
                    # 1. Log attendance (network)
                    # self.network_manager.log_attendance(user_id, name) # Incorrect call
                    transaction_id = self.db_manager.add_transaction(user_id)
                    if transaction_id:
                        # Optionally, immediately queue for faster upload attempt (NetworkManager also polls DB)
                        self.network_manager.queue_transaction(transaction_id)
                    else:
                        logger.error(f"Failed to log transaction for user {user_id} in the database.")
                        self.update_status_label(f"DB Error logging {name}", "red")

                    # 2. Activate hardware (relay/LED)
                    hw.activate_relay()
                    hw.set_led_status(True) # Green ON, Red OFF
                    # Schedule LED off after door duration (revert to default Red ON)
                    QTimer.singleShot(config.DOOR_OPEN_DURATION_SEC * 1000, lambda: hw.set_led_status(False))
                    # 3. Show temporary welcome message
                    self.show_temporary_message("Welcome!", f"Hello, {name}!", duration_ms=3000)
                    # 4. Pause recognition process
                    self.recognition_paused_until = time.time() + 4.0 # Pause for 4 seconds
                    logger.info("Recognition paused for 4 seconds.")
                    # Update display immediately to show pause state if needed
                    if self.current_primary_frame is not None:
                         self.update_video_display(self.current_primary_frame, face_locations, recognized_data, paused=True)
                    break # Process only the first recognized person fully for welcome message/pause

                else:
                    # Recognized but within cooldown
                    status_text = f"Recognized: {name} (Cooldown)"
                    status_color = "yellow"
                    logger.debug(f"Recognized {name} (ID: {user_id}) within cooldown period.")
                    # Optionally flash green LED briefly?
                    # hw.set_led('green', True)
                    # QTimer.singleShot(200, lambda: hw.set_led('green', False))

            elif name == config.UNKNOWN_PERSON_LABEL:
                status_text = f"Unknown Person Detected (Closest Dist: {distance:.2f})"
                status_color = "orange"
                hw.set_led_status(False) # Red ON, Green OFF for unknown
                # QTimer.singleShot(1000, lambda: hw.set_led('red', False)) # Turn off after 1 sec - REMOVED as next frame handles state

        if not face_locations:
            status_text = "Status: Monitoring... No faces detected."
            status_color = "white"
            hw.set_led_status(False) # Ensure default state (Red ON) if no faces

        self.update_status_label(status_text, status_color)

        # Display update is handled by handle_frame
        # if self.current_primary_frame is not None and not self.recognition_paused_until:
        #      self.update_video_display(self.current_primary_frame, face_locations, recognized_data)


    # This method is now primarily called by handle_frame
    # It still needs the @pyqtSlot decorator if connected to signals, but it's not directly connected anymore.
    # Keeping the decorator doesn't hurt, but it's not strictly necessary for its current usage.
    @pyqtSlot(str, str) # Decorator ensures it runs in the main thread
    def update_video_display(self, frame, face_locations, recognized_data, paused=False):
        """Updates the video label with the frame and drawn boxes/names."""
        try:
            display_frame = frame.copy()
            h, w, _ = display_frame.shape

            # Draw rectangles and names
            for i, (top, right, bottom, left) in enumerate(face_locations):
                color = (0, 0, 255) # Red for unknown by default
                name = config.UNKNOWN_PERSON_LABEL
                if i < len(recognized_data):
                    rec_data = recognized_data[i]
                    name = rec_data.get('name', config.UNKNOWN_PERSON_LABEL)
                    user_id = rec_data.get('id')
                    if user_id is not None:
                        # Check if within cooldown for display purposes
                        last_seen = self.last_recognition_details.get(user_id)
                        if last_seen and (datetime.now() - last_seen) < timedelta(seconds=config.RECOGNITION_COOLDOWN_SEC):
                             color = (0, 255, 255) # Yellow for recognized but cooldown
                        else:
                             color = (0, 255, 0) # Green for recognized
                    elif name != config.UNKNOWN_PERSON_LABEL: # Should have ID, but fallback
                         color = (0, 255, 0)

                # Draw rectangle
                cv2.rectangle(display_frame, (left, top), (right, bottom), color, 2)

                # Draw label
                label = f"{name}"
                if name != config.UNKNOWN_PERSON_LABEL and i < len(recognized_data):
                     distance = recognized_data[i].get('distance', 1.0)
                     label += f" ({distance:.2f})"

                # Text background
                (text_width, text_height), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
                cv2.rectangle(display_frame, (left, bottom - text_height - baseline - 5), (left + text_width, bottom), color, cv2.FILLED)
                # Text itself
                cv2.putText(display_frame, label, (left + 3, bottom - baseline), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)

            # Add "Paused" overlay if needed
            if paused:
                overlay_color = (0, 0, 0, 180) # Semi-transparent black
                text_color = (255, 255, 255, 255) # White
                font_scale = 1.5
                thickness = 2
                text = "Recognition Paused"
                (text_w, text_h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
                text_x = int((w - text_w) / 2)
                text_y = int((h + text_h) / 2)
                # Create overlay rectangle (using numpy for potential alpha blending if needed)
                sub_img = display_frame[text_y - text_h - 10:text_y + 10, text_x - 10:text_x + text_w + 10]
                white_rect = np.ones(sub_img.shape, dtype=np.uint8) * 0 # Black background
                alpha = 0.7 # Transparency factor
                res = cv2.addWeighted(sub_img, alpha, white_rect, 1-alpha, 1.0)
                display_frame[text_y - text_h - 10:text_y + 10, text_x - 10:text_x + text_w + 10] = res
                # Put text on overlay
                cv2.putText(display_frame, text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, text_color[:3], thickness, cv2.LINE_AA)


            # Convert frame to QPixmap
            rgb_image = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qt_image)
            self.video_label.setPixmap(pixmap.scaled(self.video_label.size(),
                                                    Qt.AspectRatioMode.KeepAspectRatio,
                                                    Qt.TransformationMode.SmoothTransformation))
        except Exception as e:
            logger.error(f"Error updating video display: {e}", exc_info=True)
            # Optionally display error on label itself
            # painter = QPainter(self.video_label.pixmap())
            # painter.setPen(QColor("red"))
            # painter.drawText(10, 30, f"Display Error: {e}")
            # painter.end()

    @pyqtSlot(str, str) # Decorator ensures it runs in the main thread
    def update_status_label(self, text, color="white"):
        """Updates the status label text and color."""
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color};")

    def update_ui_elements(self):
        """Periodically updates UI elements like FPS."""
        # Calculate FPS (simple average over the last second)
        # More sophisticated FPS calculation might be needed
        # This is just a placeholder
        self.fps_label.setText(f"FPS: {self.frame_counter}") # Assuming frame_counter resets or is handled elsewhere
        # Reset frame counter for the next second? Depends on how FPS is calculated.
        # self.frame_counter = 0 # If calculating FPS per second

    def on_user_registered(self):
        """Callback when registration is successful."""
        logger.info("User registration successful signal received.")
        # The dialog already reloads faces in face_processor
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
            # self.start_camera(config.SECONDARY_CAMERA_INDEX, config.FPS_LIMIT / 2)
            pass
        self.processing_active = True
        logger.info("Main camera(s) restarted and processing resumed.")


    def closeEvent(self, event):
        """Handles application closing."""
        logger.info("Close event triggered. Shutting down...")
        self.processing_active = False

        # 1. Stop worker thread
        if self.worker_thread.isRunning():
            logger.info("Stopping worker thread...")
            # self.worker.stop() # No longer needed
            self.worker_thread.quit() # Ask the thread's event loop to exit
            if not self.worker_thread.wait(3000): # Wait 3 sec
                 logger.warning("Worker thread did not quit gracefully.")


        # 2. Stop camera threads
        self.stop_all_cameras()

        # 3. Stop network manager thread
        self.network_manager.stop()

        # 4. Cleanup hardware
        hw.cleanup()

        logger.info("Shutdown complete.")
        event.accept() # Proceed with closing


# --- Main Execution ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Apply a style maybe?
    # app.setStyle('Fusion')

    main_window = MainWindow()
    main_window.show()

    sys.exit(app.exec())