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
from PyQt6.QtGui import QPixmap, QImage, QFont, QColor, QPainter, QIcon # Added QIcon
from wiegand_reader import WiegandReader # Added for Wiegand support
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread, QMutex, QMutexLocker, pyqtSlot, QUrl # Added QUrl
# from PyQt6.QtMultimedia import QSoundEffect # Removed QSoundEffect
import pygame # Added pygame
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

# --- Custom Recognition Status Dialog ---

# Define a minimum display time in seconds
MINIMUM_DIALOG_DISPLAY_TIME_SEC = 4

class RecognitionStatusDialog(QDialog):
    def __init__(self, message, status, icon_path, bg_color, sound_path, parent=None):
        super().__init__(parent)
        self.status = status # 'accepted' or 'rejected'
        self.icon_path = icon_path
        self.bg_color = bg_color # e.g., "rgba(173, 216, 230, 200)" for light blue transparent
        self.sound_path = sound_path

        self.setWindowTitle("Access Status")
        # Frameless and stay on top
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) # Enable transparency
        self.setModal(False)

        # Set a fixed size
        self.setFixedSize(400, 220) # Slightly larger for icon

        # Main layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0) # No margins for the main layout

        # Background widget for styling
        self.background_widget = QWidget(self)
        self.background_widget.setObjectName("backgroundWidget") # For styling via stylesheet
        self.background_widget.setStyleSheet(f"#backgroundWidget {{ background-color: {self.bg_color}; border-radius: 15px; }}")

        # Content layout inside the background widget
        content_layout = QVBoxLayout(self.background_widget)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(10)

        # Icon
        self.icon_label = QLabel()
        if os.path.exists(self.icon_path):
            pixmap = QPixmap(self.icon_path)
            self.icon_label.setPixmap(pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            logger.warning(f"Icon not found: {self.icon_path}")
            self.icon_label.setText("Icon?") # Placeholder
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.icon_label)

        # Status Message (e.g., "ACCESS ACCEPTED" or "ACCESS REJECTED")
        status_text = "ACCESS ACCEPTED" if self.status == 'accepted' else "ACCESS REJECTED"
        status_label = QLabel(status_text)
        status_font = QFont()
        status_font.setPointSize(16)
        status_font.setBold(True)
        status_label.setFont(status_font)
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_label.setStyleSheet(f"color: {'#27ae60' if self.status == 'accepted' else '#e74c3c'};") # Green for accepted, Red for rejected
        content_layout.addWidget(status_label)

        # User Message (Name or rejection reason)
        self.message_label = QLabel(message)
        message_font = QFont()
        message_font.setPointSize(14)
        self.message_label.setFont(message_font)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet("color: #34495e;") # Dark grey text
        content_layout.addWidget(self.message_label)

        # Add background widget to main layout
        self.main_layout.addWidget(self.background_widget)

        # Sound Effect (using pygame)
        self.pygame_sound = None
        if os.path.exists(self.sound_path):
            try:
                self.pygame_sound = pygame.mixer.Sound(self.sound_path)
            except pygame.error as e:
                logger.error(f"Error loading sound '{self.sound_path}' with pygame: {e}")
        else:
            logger.warning(f"Sound file not found: {self.sound_path}")

        # Timer to close the dialog
        self.close_timer = QTimer(self)
        self.close_timer.timeout.connect(self.accept) # Use accept to close cleanly
        self.close_timer.setSingleShot(True)

    def showEvent(self, event):
        """Play sound and start timer when dialog is shown."""
        super().showEvent(event)
        # Move to bottom-middle position after showing
        screen_geometry = QApplication.primaryScreen().geometry()
        parent_window = self.parent() # Get the main window
        if parent_window:
            # Calculate position relative to the main window if possible
            parent_rect = parent_window.geometry()
            x = parent_rect.x() + int((parent_rect.width() - self.width()) / 2)
            y = parent_rect.y() + parent_rect.height() - self.height() - 50 # 50px margin from bottom
        else:
            # Fallback to screen geometry if no parent
            x = int((screen_geometry.width() - self.width()) / 2)
            y = screen_geometry.height() - self.height() - 50 # 50px margin from bottom

        self.move(x, y)

        # Play sound (using pygame)
        if self.pygame_sound:
            try:
                self.pygame_sound.play()
            except pygame.error as e:
                logger.error(f"Error playing sound with pygame: {e}")

        # Start close timer - Ensure minimum display time
        display_duration_ms = max(config.RECOGNITION_COOLDOWN_SEC, MINIMUM_DIALOG_DISPLAY_TIME_SEC) * 1000
        logger.info(f"Starting dialog close timer for {display_duration_ms / 1000:.1f} seconds.")
        self.close_timer.start(int(display_duration_ms))

    def closeEvent(self, event):
        """Placeholder for potential cleanup if needed."""
        # No explicit stop needed for pygame.mixer.Sound typically
        # if self.pygame_sound:
        #     self.pygame_sound.stop() # Usually not required
        super().closeEvent(event)

# --- Remove Old AutoCloseDialog --- 
# class AutoCloseDialog(QDialog):
# #     # ... (Old class definition removed) ...
#     def __init__(self, message, parent=None):
#         super().__init__(parent)
#         self.setWindowTitle("Welcome")
#         self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
#         self.setModal(False)

#         # Set a fixed size for more professional appearance
#         self.setFixedSize(400, 200)

#         # Create a more professional looking layout
#         layout = QVBoxLayout()
#         layout.setContentsMargins(20, 20, 20, 20)

#         # Add a welcome header
#         header = QLabel("WELCOME")
#         header_font = QFont()
#         header_font.setPointSize(18)
#         header_font.setBold(True)
#         header.setFont(header_font)
#         header.setAlignment(Qt.AlignmentFlag.AlignCenter)
#         header.setStyleSheet("color: #2c3e50;")
#         layout.addWidget(header)

#         # Add the user's name with larger font
#         self.label = QLabel(message)
#         name_font = QFont()
#         name_font.setPointSize(24)
#         name_font.setBold(True)
#         self.label.setFont(name_font)
#         self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
#         self.label.setStyleSheet("color: #27ae60; margin: 10px;")
#         layout.addWidget(self.label)

#         # Add timestamp
#         time_label = QLabel(datetime.now().strftime("%H:%M:%S"))
#         time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
#         time_label.setStyleSheet("color: #7f8c8d; font-size: 14px;")
#         layout.addWidget(time_label)

#         # Set dialog styling
#         self.setStyleSheet("""
#             QDialog {
#                 background-color: white;
#                 border: 2px solid #3498db;
#                 border-radius: 10px;
#             }
#         """)

#         self.setLayout(layout)
#         self.show()

#         # Move to center-top position
#         screen_geometry = QApplication.primaryScreen().geometry()
#         self.move(
#             int((screen_geometry.width() - self.width()) / 2),
#             50
#         )

#         # Add a self-closing timer
#         self.close_timer = QTimer(self)
#         self.close_timer.timeout.connect(self.close)
#         self.close_timer.setSingleShot(True)

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

        # Initialize Wiegand Reader
        self.wiegand_reader = WiegandReader(pin_d0=config.WIEGAND_DATA0_PIN, pin_d1=config.WIEGAND_DATA1_PIN)
        self.wiegand_reader.card_scanned.connect(self.handle_card_scan)
        self.wiegand_reader.start()
        logger.info("Wiegand reader initialized and started.")
        
        # After self.network_manager = NetworkManager(...)
        # New Periodic User Synchronization logic
        if getattr(config, 'NETWORK_ENABLED', False) and self.network_manager and hasattr(self.network_manager, 'sync_users_from_backend'):
            self.user_sync_timer = QTimer(self)
            self.user_sync_timer.timeout.connect(self.perform_user_sync)
            sync_interval_minutes = getattr(config, 'USER_SYNC_INTERVAL_MINUTES', 30)
            sync_interval_ms = sync_interval_minutes * 60 * 1000
            if sync_interval_ms > 0:
                self.user_sync_timer.start(sync_interval_ms)
                logger.info(f"Periodic user synchronization scheduled every {sync_interval_minutes} minutes.")
                # Perform an initial sync shortly after startup
                QTimer.singleShot(5000, self.perform_user_sync) 
            else:
                logger.info("Periodic user synchronization disabled (interval <= 0 minutes).")
        elif getattr(config, 'NETWORK_ENABLED', False):
            logger.warning("Network features enabled, but NetworkManager may not be fully initialized or 'sync_users_from_backend' method is missing. Periodic sync disabled.")
        else:
            logger.info("Network features are disabled. User synchronization will not occur.")

        # --- State Variables ---
        self.last_known_face_locations = []
        self.last_recognized_data = []
        self.last_frame_time = time.time()
        self.frame_counter = 0
        self.current_primary_frame = None # Store latest frame from primary cam
        self.last_recognition_details = {} # Store last recognition time per user ID
        self.processing_active = True # Flag to control processing
        self.recognition_paused_until = None # Timestamp until which recognition is paused
        # self.welcome_dialog = None # Changed from message_box to dialog - REMOVE this line, handled differently now
        self.current_status_dialog = None # To keep track of the currently displayed status dialog

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

        # --- Initialize Pygame Mixer ---
        try:
            pygame.mixer.init()
            logger.info("Pygame mixer initialized successfully.")
        except pygame.error as e:
            logger.error(f"Failed to initialize pygame mixer: {e}", exc_info=True)
            QMessageBox.warning(self, "Audio Error", f"Could not initialize audio subsystem: {e}\nSounds will be disabled.")

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

    @pyqtSlot(str)
    def handle_card_scan(self, card_number):
        logger.info(f"Card scanned: {card_number}")

        # Check if recognition is paused (e.g., by a recent facial recognition)
        now = time.time()
        if self.recognition_paused_until and now < self.recognition_paused_until:
            logger.info(f"Card scan for {card_number} ignored due to active cooldown.")
            return

        user_data = self.db_manager.get_user_by_card_number(card_number)

        if user_data:
            user_id = user_data['id']
            name = user_data['name']
            logger.info(f"Card scan matched user: {name} (ID: {user_id})")

            # Cooldown logic for card scans (can be separate or shared)
            # For simplicity, let's use the existing facial recognition cooldown
            last_rec_time = self.last_recognition_details.get(f"card_{user_id}", 0) # Use a distinct key for card
            if now - last_rec_time > config.RECOGNITION_COOLDOWN_SEC:
                self.last_recognition_details[f"card_{user_id}"] = now

                transaction_id = self.db_manager.add_transaction(user_id, method="card") # Add method
                if transaction_id:
                    self.network_manager.queue_transaction(transaction_id)
                else:
                    logger.error(f"Failed to log card transaction for user {user_id}")

                hw.activate_relay()
                self.update_status_label(f"Welcome, {name}! (Card)", "green")

                # Show Accepted Dialog (similar to facial recognition)
                script_dir = os.path.dirname(os.path.abspath(__file__))
                media_dir = os.path.join(script_dir, 'media')
                message = f"Welcome, {name}!\n(Card Access)"
                status = 'accepted'
                icon_path = os.path.join(media_dir, "accept.png")
                bg_color = "rgba(173, 216, 230, 200)"
                sound_path = os.path.join(media_dir, "access accepted.wav")

                if self.current_status_dialog:
                    self.current_status_dialog.close()
                self.current_status_dialog = RecognitionStatusDialog(message, status, icon_path, bg_color, sound_path, self)
                self.current_status_dialog.show()
                
                self.pause_processing(config.RECOGNITION_COOLDOWN_SEC) # Pause facial rec
            else:
                logger.debug(f"User {name} (Card ID: {card_number}) scanned again within cooldown. Skipping.")
        else:
            logger.warning(f"Card scan {card_number} did not match any user.")
            self.update_status_label("Access Denied: Card Not Registered", "red")

            # Show Rejected Dialog
            script_dir = os.path.dirname(os.path.abspath(__file__))
            media_dir = os.path.join(script_dir, 'media')
            message = "Access Rejected: Card Not Registered."
            status = 'rejected'
            icon_path = os.path.join(media_dir, "rejected.png")
            bg_color = "rgba(255, 192, 203, 200)"
            sound_path = os.path.join(media_dir, "access rejected.wav")

            if self.current_status_dialog:
                self.current_status_dialog.close()
            self.current_status_dialog = RecognitionStatusDialog(message, status, icon_path, bg_color, sound_path, self)
            self.current_status_dialog.show()

            self.pause_processing(config.RECOGNITION_COOLDOWN_SEC) # Pause facial rec

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
        
        # Pause processing while user management is open
        self.processing_active = False
        self.stop_all_cameras()
        
        dialog = UserManagementDialog(self.db_manager, self.face_processor, self)
        # Connect the signal to a slot if needed (e.g., to refresh UI elements)
        dialog.users_changed.connect(self.handle_users_changed)
        dialog.exec()
        
        # Resume processing after dialog closes
        self.processing_active = True
        QTimer.singleShot(500, lambda: self.start_camera(config.PRIMARY_CAMERA_INDEX, config.FPS_LIMIT))

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

    def perform_user_sync(self):
        logger.info("Attempting periodic user synchronization with backend...")
        if not getattr(config, 'NETWORK_ENABLED', False) or \
           not self.network_manager or \
           not hasattr(self.network_manager, 'sync_users_from_backend'):
            logger.debug("User synchronization skipped (network disabled, NetworkManager missing, or sync method unavailable).")
            return

        try:
            users_updated_result = self.network_manager.sync_users_from_backend()
            if users_updated_result:
                logger.info(f"User data synchronized from backend. Reloading local data.")
                self.handle_users_changed()
                self.update_status_label("User data updated from server.", "blue")
            else:
                logger.info("No user data changes from backend during sync.")
        except Exception as e:
            logger.error(f"Error during periodic user synchronization: {e}", exc_info=True)
            self.update_status_label("Error: User sync failed.", "red")

    def closeEvent(self, event):
        """Handle cleanup on window close."""
        logger.info("Main window closing. Stopping threads and cleaning up.")
        self.stop_all_cameras()
        if self.network_manager:
            self.network_manager.stop()
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait(1000) # Wait a bit for clean exit

        # Quit pygame mixer
        pygame.mixer.quit()
        logger.info("Pygame mixer quit.")

        super().closeEvent(event)


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
        """Handles incoming frames from a camera thread."""
        if not self.processing_active:
            return # Don't process if paused

        if cam_index == config.PRIMARY_CAMERA_INDEX:
            self.current_primary_frame = frame # Store latest primary frame
            self.frame_count_since_last_update += 1
            now = time.time()

            # Check if recognition is paused
            if self.recognition_paused_until and now < self.recognition_paused_until:
                # self.update_video_display(frame, [], [], paused=True)
                self._update_video_label(frame, [], [], paused=True) # Use new method
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
                 # self.update_video_display(frame, self.last_known_face_locations, self.last_recognized_data)
                 self._update_video_label(frame, self.last_known_face_locations, self.last_recognized_data) # Use new method
            else:
                 # Still paused, ensure display shows clean frame
                 # self.update_video_display(frame, [], [], paused=True)
                 self._update_video_label(frame, [], [], paused=True) # Use new method

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
        # --- Check if a status dialog is already visible --- 
        if self.current_status_dialog and self.current_status_dialog.isVisible():
            logger.debug("Recognition result received while status dialog is visible. Ignoring.")
            return # Ignore new result if a dialog is already showing

        # Close any *non-visible* or finished dialog reference (cleanup)
        if self.current_status_dialog:
            self.current_status_dialog.close() # Ensure any lingering reference is closed
            self.current_status_dialog = None

        self.last_known_face_locations = face_locations
        self.last_recognized_data = recognized_data

        # Update display immediately with new results (handled by handle_frame now)
        # self.update_video_display(self.current_primary_frame, face_locations, recognized_data)

        now = time.time()
        processed_ids_this_cycle = set()
        recognition_occurred = False # Initialize the flag here

        for data in recognized_data:
            user_id = data['id']
            name = data['name']
            distance = data['distance']

            if user_id is not None: # Known user
                recognition_occurred = True
                last_rec_time = self.last_recognition_details.get(user_id, 0)

                if now - last_rec_time > config.RECOGNITION_COOLDOWN_SEC:
                    logger.info(f"Recognized known user: {name} (ID: {user_id}), Distance: {distance:.2f}")
                    self.last_recognition_details[user_id] = now
                    # Log transaction in DB first
                    transaction_id = self.db_manager.add_transaction(user_id, method="face") # Add method="face"
                    if transaction_id:
                        # Queue the transaction for network upload
                        self.network_manager.queue_transaction(transaction_id)
                    else:
                        logger.error(f"Failed to log transaction for user {user_id}")
                    hw.activate_relay()
                    self.update_status_label(f"Welcome, {name}!", "green")

                    # --- Show Accepted Dialog --- 
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    media_dir = os.path.join(script_dir, 'media')
                    message = f"Welcome, {name}!"
                    status = 'accepted'
                    icon_path = os.path.join(media_dir, "accept.png")
                    bg_color = "rgba(173, 216, 230, 200)" # Light blue transparent
                    sound_path = os.path.join(media_dir, "access accepted.wav")

                    if self.current_status_dialog:
                        self.current_status_dialog.close() # Close previous if any
                    self.current_status_dialog = RecognitionStatusDialog(message, status, icon_path, bg_color, sound_path, self)
                    self.current_status_dialog.show()
                    # --- End Show Accepted Dialog ---

                    # Pause processing briefly after successful recognition
                    self.pause_processing(config.RECOGNITION_COOLDOWN_SEC)
                    break # Process only the first recognized known user per frame
                else:
                    logger.debug(f"User {name} (ID: {user_id}) recognized again within cooldown period. Skipping actions.")

            elif name == config.UNKNOWN_PERSON_LABEL:
                # Handle unknown person detection only if no known person was recognized in this frame
                # And if processing is not paused
                if not recognition_occurred and (self.recognition_paused_until is None or now > self.recognition_paused_until):
                    logger.info(f"Unknown person detected. Distance to closest match: {distance:.2f}")
                    self.update_status_label("Access Denied: Unknown User", "red")

                    # --- Show Rejected Dialog --- 
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    media_dir = os.path.join(script_dir, 'media')
                    message = "Access Rejected: You are not registered."
                    status = 'rejected'
                    icon_path = os.path.join(media_dir, "rejected.png")
                    bg_color = "rgba(255, 192, 203, 200)" # Light red/pink transparent
                    sound_path = os.path.join(media_dir, "access rejected.wav") # Corrected typo and path

                    if self.current_status_dialog:
                        self.current_status_dialog.close() # Close previous if any
                    self.current_status_dialog = RecognitionStatusDialog(message, status, icon_path, bg_color, sound_path, self)
                    self.current_status_dialog.show()
                    # --- End Show Rejected Dialog ---

                    # Pause processing after showing rejection message
                    self.pause_processing(config.RECOGNITION_COOLDOWN_SEC)
                    break # Stop processing further faces in this frame if unknown is detected

        # If no faces were detected at all
        if not face_locations and not recognized_data and (self.recognition_paused_until is None or now > self.recognition_paused_until):
            self.update_status_label("Status: Looking for faces...", "white")

        # Update the main camera feed display (if needed, or handled elsewhere)
        # self.update_camera_feed(self.current_primary_frame, config.PRIMARY_CAMERA_INDEX) # Might be redundant if update happens on frame arrival

    def pause_processing(self, duration_seconds):
        """Pauses face processing for a specified duration."""
        self.recognition_paused_until = time.time() + duration_seconds
        self.last_known_face_locations = [] # Clear boxes while paused
        self.last_recognized_data = []
        logger.info(f"Recognition paused for {duration_seconds} seconds.")
        # Optionally update status
        self.update_status_label(f"Recognition paused...", "orange")
        # Ensure the camera feed updates to clear boxes
        if self.current_primary_frame is not None:
             self._update_video_label(self.current_primary_frame, [], [], paused=True) # Use new method

    def handle_card_scan(self, card_number):
        """Handles card scans from the Wiegand reader."""
        logger.info(f"Card scanned: {card_number}")
        if self.recognition_paused_until and time.time() < self.recognition_paused_until:
            logger.info("Card scan ignored due to active cooldown/pause.")
            # Optionally provide feedback that the system is busy
            # self.show_temporary_message("System busy, please try again shortly.", duration_ms=2000, is_error=True)
            return

        user_info = self.db_manager.get_user_by_card_number(card_number)

        if user_info:
            user_id, name, _ = user_info
            logger.info(f"Card matched: User {name} (ID: {user_id})")
            self.db_manager.log_transaction(user_id, "card_scan_accepted", card_number)
            self.show_recognition_dialog(True, name, card_scan=True)
            self.pause_processing(config.RECOGNITION_COOLDOWN_SEC) # Pause after card scan too
        else:
            logger.warning(f"Card not recognized: {card_number}")
            self.db_manager.log_transaction(None, "card_scan_rejected", card_number)
            self.show_recognition_dialog(False, "Unknown Card", card_scan=True)
            self.pause_processing(config.UNKNOWN_PERSON_COOLDOWN_SEC) # Longer pause for unknown card


    def update_status_label(self, message, color="white"):
        """Updates the status bar message with a given color."""
        try:
            # Set text color based on the 'color' parameter
            self.statusbar.setStyleSheet(f"QStatusBar {{ color: {color}; }}")
            self.statusbar.showMessage(message, 0) # timeout=0 means permanent until next message
            logger.debug(f"Status updated: {message}")
        except AttributeError:
            logger.warning("Status bar not found or not yet initialized.")
        except Exception as e:
            logger.error(f"Error updating status bar: {e}", exc_info=True)


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


    def _update_video_label(self, frame, face_locations, recognized_data, paused=False):
        """Updates the video display label (imgLable) with the current frame and overlays."""
        try:
            if frame is None:
                # Attempt to set a default text if the label exists
                if hasattr(self, 'imgLable'):
                    self.imgLable.setText("No frame received")
                else:
                    logger.warning("imgLable not found during frame update.")
                return

            display_frame = frame.copy()
            h, w, ch = display_frame.shape
            bytes_per_line = ch * w

            if paused:
                # Optionally display a pause indicator
                cv2.putText(display_frame, "", (w // 2 - 50, h // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)
            else:
                # Draw rectangles and names for recognized faces
                # Ensure recognized_data contains tuples or lists of the expected structure
                for loc, data in zip(face_locations, recognized_data):
                    if isinstance(data, dict):
                        name = data.get('name', 'Unknown')
                    elif isinstance(data, (list, tuple)) and len(data) >= 2:
                        name = data[1] # Assuming name is the second element
                    else:
                        name = 'Unknown' # Default if format is unexpected
                    
                    top, right, bottom, left = loc
                    # Draw a box around the face
                    cv2.rectangle(display_frame, (left, top), (right, bottom), (0, 255, 0), 2)

                    # Draw a label with a name below the face
                    cv2.rectangle(display_frame, (left, bottom - 25), (right, bottom), (0, 255, 0), cv2.FILLED)
                    font = cv2.FONT_HERSHEY_DUPLEX
                    display_name = name if name != config.UNKNOWN_PERSON_LABEL else "Unknown"
                    cv2.putText(display_frame, display_name, (left + 6, bottom - 6), font, 0.8, (255, 255, 255), 1)

            # Convert the image to QImage
            rgb_image = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qt_image)

            # Scale pixmap to fit the label while maintaining aspect ratio
            if hasattr(self, 'imgLable'):
                scaled_pixmap = pixmap.scaled(self.imgLable.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.imgLable.setPixmap(scaled_pixmap)
            else:
                logger.warning("imgLable not found, cannot set pixmap.")

        except Exception as e:
            logger.error(f"Error updating video label: {e}", exc_info=True)
            if hasattr(self, 'imgLable'):
                self.imgLable.setText("Error displaying frame")

    def closeEvent(self, event):
        """Ensure cleanup on application close."""
        logger.info("MainWindow closeEvent triggered. Cleaning up...")
        self.processing_active = False # Stop processing first

        # Stop timers
        if hasattr(self, 'ui_update_timer') and self.ui_update_timer.isActive():
            self.ui_update_timer.stop()
            logger.debug("UI Update Timer stopped.")
        if hasattr(self, 'user_sync_timer') and self.user_sync_timer.isActive():
            self.user_sync_timer.stop()
            logger.debug("User Sync Timer stopped.")

        # Stop hardware components (Wiegand Reader)
        if hasattr(self, 'wiegand_reader') and self.wiegand_reader:
            if hasattr(self.wiegand_reader, 'stop'):
                logger.debug("Stopping Wiegand reader...")
                self.wiegand_reader.stop()
                logger.debug("Wiegand reader stopped.")
            else:
                logger.warning("Wiegand reader does not have a stop method.")

        # Stop threads (Worker, NetworkManager)
        if hasattr(self, 'worker_thread') and self.worker_thread.isRunning():
            logger.debug("Stopping worker thread...")
            self.worker_thread.quit()
            if not self.worker_thread.wait(2000):
                 logger.warning("Worker thread did not finish quitting gracefully. Forcing termination.")
                 self.worker_thread.terminate()
                 self.worker_thread.wait()
            logger.debug("Worker thread stopped.")

        if hasattr(self, 'network_manager') and hasattr(self.network_manager, 'stop'):
             logger.debug("Stopping network manager...")
             self.network_manager.stop()
             logger.debug("Network manager stopped.")

        # Close dialogs
        if hasattr(self, 'welcome_dialog') and self.welcome_dialog:
            self.welcome_dialog.close()
            logger.debug("Welcome dialog closed.")
        if hasattr(self, 'current_status_dialog') and self.current_status_dialog and self.current_status_dialog.isVisible():
            self.current_status_dialog.close()
            logger.debug("Current status dialog closed.")

        # Quit Pygame mixer
        if 'pygame.mixer' in sys.modules and pygame.mixer.get_init():
            pygame.mixer.quit()
            logger.info("Pygame mixer quit.")
        
        # Stop and wait for all camera threads
        logger.info("Stopping and waiting for all camera threads...")
        self.stop_all_cameras() # Signals all camera threads to stop
        
        # Create a list of threads to wait for to avoid issues with dict changing during iteration
        threads_to_wait_for = list(self.camera_threads.values())
        for thread in threads_to_wait_for:
            if thread.isRunning():
                cam_idx = getattr(thread, 'camera_index', 'N/A')
                logger.debug(f"Waiting for camera thread (index: {cam_idx}) to finish...")
                if not thread.wait(1500): # Wait for 1.5 seconds
                    logger.warning(f"Camera thread (index: {cam_idx}) did not finish gracefully. Terminating.")
                    thread.terminate()
                    thread.wait() # Wait after terminate
        logger.info("All camera threads processed for shutdown.")

        logger.info("Cleanup complete. Exiting application.")
        event.accept()


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