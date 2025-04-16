# main.py
import sys
import cv2
import numpy as np
import time
import logging
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QSizePolicy)
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

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, # Change to DEBUG for more detail
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# --- End Logging Setup ---


# --- Worker thread for blocking tasks like recognition and relay ---
class Worker(QObject):
    finished = pyqtSignal()
    # Signal to update UI with recognition results
    recognition_result = pyqtSignal(list, list, bool) # face_locations, recognized_data, is_live
    # Signal to update status message
    status_update = pyqtSignal(str, str) # message, color ('black', 'green', 'red', 'orange')

    def __init__(self, face_processor: FaceProcessor):
        super().__init__()
        self.face_processor = face_processor
        # No current_frame_rgb or frame_count needed here now
        logger.info("Worker object initialized.")

    # Make process_this_frame the SLOT that does the work when signaled
    @pyqtSlot(object, int) # Decorate as a slot
    def process_this_frame(self, frame_rgb, frame_count):
        """Processes the received frame and emits results."""
        # Removed the mutex and _running flag logic
        if frame_rgb is None:
             logger.warning("Worker received None frame.")
             return

        try:
            logger.debug(f"Worker processing frame {frame_count}")
            # Perform detection, liveness check, and recognition directly here
            face_locations, recognized_data, is_live = self.face_processor.process_frame(
                frame_rgb, frame_count
            )
            # Emit results back to main thread for UI update
            self.recognition_result.emit(face_locations, recognized_data, is_live)
            logger.debug(f"Worker finished frame {frame_count}")
        except Exception as e:
            logger.error(f"Error during face processing in worker: {e}", exc_info=True)
            # Emit status update on error
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

        # Optional: Connect thread finished signals for cleanup
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self.worker_thread.start() # Start the thread's event loop
        logger.info("Worker thread started.")
        # self.worker.finished.connect(self.worker_thread.quit) # Maybe manage thread lifecycle differently
        # self.worker.finished.connect(self.worker.deleteLater)
        # self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        
        self.request_processing.connect(self.worker.process_this_frame)

        self.worker_thread.start()
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


    def handle_camera_error(self, error_msg, index):
        logger.error(f"Camera {index} Error: {error_msg}")
        self.update_status_label(f"Camera {index} Error: {error_msg}", "red")
        # Optionally try to restart the camera thread after a delay
        if index in self.camera_threads:
             del self.camera_threads[index] # Remove faulty thread
        # QTimer.singleShot(5000, lambda: self.start_camera(index, config.FPS_LIMIT)) # Retry after 5s


    def handle_frame(self, frame, camera_index):
        """Receives frame from any camera thread."""
        if camera_index == config.PRIMARY_CAMERA_INDEX:
            self.current_primary_frame = frame # Store the latest primary frame
            # --- Frame Processing Trigger ---
            current_time = time.time()
            # Limit processing frequency
            if self.processing_active and (current_time - self.last_frame_time >= 1.0 / config.FPS_LIMIT):
                self.last_frame_time = current_time
                self.frame_counter += 1

                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frame_rgb_small = cv2.resize(frame_rgb, (config.FRAME_WIDTH, config.FRAME_HEIGHT))

                # Emit the signal to trigger the worker's process_this_frame slot
                self.request_processing.emit(frame_rgb_small, self.frame_counter) # <--- Triggers worker

            # --- Display Update (always update display) ---
            self.display_frame(frame)# Display the original res frame

        # elif camera_index == config.SECONDARY_CAMERA_INDEX:
        #     # Handle secondary camera frame (e.g., display in a corner, use for liveness)
        #     pass


    def handle_recognition_result(self, face_locations, recognized_data, is_live):
        """Receives recognition results from worker thread and updates state/UI."""
        self.last_known_face_locations = face_locations
        self.last_recognized_data = recognized_data

        identified = False
        status_msg = "Status: Looking for faces..."
        status_color = "black"

        current_time = datetime.now()

        if recognized_data: # If any faces were processed (even unknown/not live)
            if is_live:
                found_match = False
                for data in recognized_data:
                    user_id = data['id']
                    name = data['name']

                    if user_id is not None and name != config.UNKNOWN_PERSON_LABEL:
                        found_match = True
                        # --- Cooldown Check ---
                        last_recog_time = self.last_recognition_details.get(user_id)
                        if last_recog_time and (current_time - last_recog_time) < timedelta(seconds=config.RECOGNITION_COOLDOWN_SEC):
                             logger.debug(f"User {name} (ID: {user_id}) is in cooldown period.")
                             status_msg = f"Welcome back, {name}!" # Show welcome but don't re-trigger
                             status_color = "green"
                             identified = True # Still considered identified for LED
                             continue # Skip triggering actions for this user


                        # --- Actions for Newly Identified User ---
                        logger.info(f"User Identified: {name} (ID: {user_id}, Distance: {data['distance']:.2f})")
                        status_msg = f"Access Granted: Welcome, {name}!"
                        status_color = "green"
                        identified = True
                        self.last_recognition_details[user_id] = current_time # Update last recognition time

                        # 1. Log Transaction
                        transaction_id = self.db_manager.add_transaction(user_id)
                        if transaction_id:
                            # 2. Queue for Network Send
                            self.network_manager.queue_transaction(transaction_id)

                        # 3. Activate Relay (in a separate thread to avoid blocking)
                        # Use QTimer.singleShot or another thread for HW actions
                        QTimer.singleShot(0, hw.activate_relay) # Runs activate_relay in the event loop briefly

                        # Break after first successful identification or process all? Process all for now.
                        # break # Uncomment if only one person should trigger door per frame

                if not found_match:
                     # Live face(s) detected, but none matched known users
                     status_msg = "Status: Unknown face detected."
                     status_color = "orange"
                     identified = False # Treat unknown as not identified for door/LED
            else:
                # Liveness check failed
                status_msg = "Status: Please look directly at the camera (Liveness check failed)."
                status_color = "orange"
                identified = False

        # Update status label and LED based on whether *any* valid identification occurred
        self.update_status_label(status_msg, status_color)
        hw.set_led_status(identified) # Update hardware LED

        # Trigger a display update with the new boxes/names
        if self.current_primary_frame is not None:
            self.display_frame(self.current_primary_frame)


    def display_frame(self, frame):
        """Displays the frame in the video label, drawing boxes and names."""
        try:
            display_frame = frame.copy()
            h, w, _ = display_frame.shape

            # Scale locations from processing size back to original frame size
            proc_h, proc_w = config.FRAME_HEIGHT, config.FRAME_WIDTH
            scale_y = h / proc_h
            scale_x = w / proc_w

            # Draw boxes and names based on the *last known results*
            for i, (top, right, bottom, left) in enumerate(self.last_known_face_locations):
                # Scale coordinates
                top = int(top * scale_y)
                right = int(right * scale_x)
                bottom = int(bottom * scale_y)
                left = int(left * scale_x)

                name = config.UNKNOWN_PERSON_LABEL
                color = (0, 0, 255) # Red for unknown/failed liveness

                if i < len(self.last_recognized_data):
                    recog_data = self.last_recognized_data[i]
                    name = recog_data['name']
                    if recog_data['id'] is not None and not "Liveness?" in name:
                         color = (0, 255, 0) # Green for known
                         # Add distance to name for debugging?
                         # name += f" ({recog_data['distance']:.2f})"
                    elif "Liveness?" in name:
                         color = (0, 165, 255) # Orange for failed liveness


                # Draw rectangle around the face
                cv2.rectangle(display_frame, (left, top), (right, bottom), color, 2)

                # Draw label with name below the face
                # Ensure text stays within frame boundaries
                text_y = bottom + 25 if bottom + 25 < h else top - 10
                cv2.rectangle(display_frame, (left, bottom - 20), (right, bottom), color, cv2.FILLED)
                font = cv2.FONT_HERSHEY_DUPLEX
                cv2.putText(display_frame, name, (left + 6, bottom - 6), font, 0.6, (255, 255, 255), 1)

            # Convert frame to QPixmap for display
            rgb_image = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            qt_image = QImage(rgb_image.data, w, h, rgb_image.strides[0], QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qt_image)

            # Scale pixmap to fit label while maintaining aspect ratio
            self.video_label.setPixmap(pixmap.scaled(self.video_label.size(),
                                                      Qt.AspectRatioMode.KeepAspectRatio,
                                                      Qt.TransformationMode.SmoothTransformation))
        except Exception as e:
            logger.error(f"Error displaying frame: {e}", exc_info=True)
            # Optionally display an error image or message on the label


    def update_status_label(self, message, color_name="black"):
        """Updates the status label text and color."""
        self.status_label.setText(message)
        color_map = {
            "black": "#000000",
            "green": "#00AA00",
            "red": "#AA0000",
            "orange": "#FFA500",
            "blue": "#0000AA",
        }
        self.status_label.setStyleSheet(f"color: {color_map.get(color_name, '#000000')};")

    def update_ui_elements(self):
        """Periodically update elements like FPS."""
        # Calculate FPS (Simple average over the last second)
        # Note: self.frame_counter increments when a frame is *sent* for processing
        # A more accurate FPS would measure frames *displayed* or *received*
        # This FPS reflects processing rate, not camera rate.
        # Resetting frame counter logic might be needed depending on desired FPS metric.
        # For now, just display a placeholder or a simple count.
        # self.fps_label.setText(f"Processed FPS: {self.frame_counter}") # Needs reset logic
        self.fps_label.setText(f"Time: {datetime.now():%H:%M:%S}") # Display time instead


    def open_registration_dialog(self):
        """Pauses processing and opens the registration dialog."""
        logger.info("Opening registration dialog.")
        self.processing_active = False # Pause processing
        self.stop_all_cameras() # Stop main cameras before opening dialog's camera

        dialog = RegistrationDialog(self.db_manager, self.face_processor, self)
        dialog.user_registered.connect(self.on_user_registered) # Connect signal
        dialog.finished.connect(self.on_registration_dialog_closed) # Signal for when dialog closes
        dialog.exec() # Show dialog modally


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