# registration_dialog.py
import cv2
import numpy as np
import config
import logging
import face_recognition
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QMessageBox, QWidget,QApplication)
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

# Assuming face_processor handles encoding generation
from face_processor import FaceProcessor
from on_screen_keyboard import OnScreenKeyboard
from camera_thread import CameraThread # To get camera feed

logger = logging.getLogger(__name__)

class RegistrationDialog(QDialog):
    user_registered = pyqtSignal() # Signal emitted when user is successfully registered

    def __init__(self, db_manager, face_processor: FaceProcessor, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.face_processor = face_processor
        self.setWindowTitle("Register New User")
        self.setModal(True) # Block main window interaction

        # State variables
        self.current_frame = None
        self.captured_encoding = None
        self.face_location = None # Store location of the face used for encoding

        # UI Elements
        self._setup_ui()

        # On-Screen Keyboard
        self.keyboard = OnScreenKeyboard()
        self.main_layout.addWidget(self.keyboard) # Add keyboard to layout

        # Connect keyboard focus
        self.name_input.installEventFilter(self)
        self.details_input.installEventFilter(self)
        self.keyboard.set_target_lineEdit(self.name_input) # Default target

        # Camera Feed Setup (Use a separate thread or timer for preview)
        # Option 1: Use a QTimer to grab frames (simpler, might block if capture is slow)
        # self.preview_timer = QTimer(self)
        # self.preview_timer.timeout.connect(self.update_preview)
        # self._capture_preview = cv2.VideoCapture(config.PRIMARY_CAMERA_INDEX)

        # Option 2: Reuse CameraThread concept (better for responsiveness)
        # For simplicity in the dialog, let's assume the main window manages the camera
        # and we can request a frame or rely on its updates if possible.
        # OR, start a temporary camera thread just for registration. Let's do that.
        self.reg_camera_thread = None
        self._start_registration_camera()

        self.setMinimumSize(800, 600) # Adjust size as needed

    def _setup_ui(self):
        self.main_layout = QVBoxLayout(self)

        # Camera Preview Area
        self.preview_label = QLabel("Initializing Camera...")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(320, 240) # Smaller preview
        self.preview_label.setStyleSheet("background-color: black; color: white;")
        self.main_layout.addWidget(self.preview_label)

        # Form Layout
        form_layout = QHBoxLayout()
        input_layout = QVBoxLayout()

        self.name_label = QLabel("Name:")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter user's full name")
        input_layout.addWidget(self.name_label)
        input_layout.addWidget(self.name_input)

        self.details_label = QLabel("Details (Optional):")
        self.details_input = QLineEdit()
        self.details_input.setPlaceholderText("e.g., Department, ID number")
        input_layout.addWidget(self.details_label)
        input_layout.addWidget(self.details_input)

        form_layout.addLayout(input_layout)

        # Action Buttons Layout
        action_layout = QVBoxLayout()
        self.capture_button = QPushButton("Capture Face")
        self.capture_button.clicked.connect(self.capture_face_encoding)
        action_layout.addWidget(self.capture_button)

        self.status_label = QLabel("Status: Aim camera at face and click Capture.")
        self.status_label.setWordWrap(True)
        action_layout.addWidget(self.status_label)

        form_layout.addLayout(action_layout)
        self.main_layout.addLayout(form_layout)


        # Dialog Buttons (Save/Cancel)
        button_layout = QHBoxLayout()
        self.save_button = QPushButton("Save User")
        self.save_button.setEnabled(False) # Disabled until face is captured
        self.save_button.clicked.connect(self.save_user)
        button_layout.addWidget(self.save_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject) # Close dialog
        button_layout.addWidget(self.cancel_button)

        self.main_layout.addLayout(button_layout)

    def eventFilter(self, source, event):
        """Event filter to set keyboard target on focus."""
        if event.type() == event.Type.FocusIn:
            if source is self.name_input:
                self.keyboard.set_target_lineEdit(self.name_input)
            elif source is self.details_input:
                self.keyboard.set_target_lineEdit(self.details_input)
        return super().eventFilter(source, event)

    def _start_registration_camera(self):
        if self.reg_camera_thread is None or not self.reg_camera_thread.isRunning():
             self.reg_camera_thread = CameraThread(config.PRIMARY_CAMERA_INDEX, target_fps=10)
             self.reg_camera_thread.frame_ready.connect(self._update_preview_frame)
             self.reg_camera_thread.error.connect(self._handle_camera_error)
             self.reg_camera_thread.start()
             logger.info("Registration camera thread started.")

    def _stop_registration_camera(self):
         if self.reg_camera_thread and self.reg_camera_thread.isRunning():
              logger.info("Stopping registration camera thread.")
              self.reg_camera_thread.stop()
              # self.reg_camera_thread.wait() # Ensure it stops before dialog closes (handled in closeEvent)
              self.reg_camera_thread = None


    def _handle_camera_error(self, error_msg, cam_index):
         logger.error(f"Registration Camera Error (Cam {cam_index}): {error_msg}")
         self.preview_label.setText(f"Camera Error:\n{error_msg}")
         self.capture_button.setEnabled(False)


    def _update_preview_frame(self, frame, cam_index):
        """Receives frame from camera thread and updates preview."""
        if cam_index != config.PRIMARY_CAMERA_INDEX: return # Ignore other cameras if any

        self.current_frame = frame # Store the latest frame for capture
        try:
            # Resize for display if needed
            display_frame = cv2.resize(frame, (320, 240)) # Match label size

            # Draw a rectangle if a face was previously captured here
            if self.face_location:
                 top, right, bottom, left = self.face_location
                 # Scale location to display size
                 h, w, _ = frame.shape
                 disp_h, disp_w = 240, 320
                 top = int(top * disp_h / h)
                 right = int(right * disp_w / w)
                 bottom = int(bottom * disp_h / h)
                 left = int(left * disp_w / w)
                 cv2.rectangle(display_frame, (left, top), (right, bottom), (0, 255, 0), 2) # Green box

            # Convert frame to QPixmap
            rgb_image = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qt_image)
            self.preview_label.setPixmap(pixmap)

        except Exception as e:
            logger.error(f"Error updating registration preview: {e}")
            self.preview_label.setText("Preview Error") # Show error on label


    def capture_face_encoding(self):
        """Captures the current frame and extracts the face encoding."""
        if self.current_frame is None:
            self.status_label.setText("Status: Camera not ready.")
            QMessageBox.warning(self, "Capture Error", "Camera frame not available.")
            return

        self.status_label.setText("Status: Processing face...")
        QApplication.processEvents() # Update UI

        frame_rgb = cv2.cvtColor(self.current_frame, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(frame_rgb, model="hog") # Use hog for speed

        if not face_locations:
            self.status_label.setText("Status: No face detected. Try again.")
            QMessageBox.warning(self, "Capture Error", "No face detected in the frame.")
            self.captured_encoding = None
            self.face_location = None
            self.save_button.setEnabled(False)
            return

        if len(face_locations) > 1:
            # Option 1: Ask user to ensure only one face is present
            # QMessageBox.warning(self, "Capture Error", "Multiple faces detected. Please ensure only one person is in the frame.")
            # self.status_label.setText("Status: Multiple faces detected.")
            # return

             # Option 2: Use the largest face (more user-friendly)
             logger.info("Multiple faces detected, selecting the largest one.")
             largest_face_idx = -1
             max_area = 0
             for i, (top, right, bottom, left) in enumerate(face_locations):
                 area = (bottom - top) * (right - left)
                 if area > max_area:
                     max_area = area
                     largest_face_idx = i

             face_locations = [face_locations[largest_face_idx]] # Keep only the largest

        # Ensure only one face location remains after filtering
        if len(face_locations) != 1:
             # This case should ideally not be reached if logic above is correct
             logger.error("Error selecting largest face.")
             self.status_label.setText("Status: Error processing multiple faces.")
             self.captured_encoding = None
             self.face_location = None
             self.save_button.setEnabled(False)
             return


        # Calculate encoding for the single detected (or largest) face
        face_encodings = face_recognition.face_encodings(frame_rgb, face_locations)

        if not face_encodings:
             # Should not happen if location was found, but check anyway
            self.status_label.setText("Status: Could not generate face encoding. Try again.")
            QMessageBox.warning(self, "Capture Error", "Failed to generate encoding for the detected face.")
            self.captured_encoding = None
            self.face_location = None
            self.save_button.setEnabled(False)
            return

        self.captured_encoding = face_encodings[0] # Get the first (and only) encoding
        self.face_location = face_locations[0] # Store location for visual feedback
        self.status_label.setText("Status: Face captured successfully! Enter details and save.")
        self.save_button.setEnabled(True)
        logger.info("Face encoding captured successfully for registration.")

        # Update preview immediately to show the captured face box
        self._update_preview_frame(self.current_frame, config.PRIMARY_CAMERA_INDEX)


    def save_user(self):
        """Validates input and saves the user to the database."""
        name = self.name_input.text().strip()
        details = self.details_input.text().strip()

        if not name:
            QMessageBox.warning(self, "Input Error", "Name cannot be empty.")
            return

        if self.captured_encoding is None:
            QMessageBox.warning(self, "Input Error", "No face encoding has been captured.")
            return

        # Confirmation dialog (optional but recommended)
        reply = QMessageBox.question(self, 'Confirm Save',
                                       f"Save user '{name}' with the captured face?",
                                       QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
                                       QMessageBox.StandardButton.Cancel)

        if reply == QMessageBox.StandardButton.Save:
            user_id = self.db_manager.add_user(name, details, self.captured_encoding)
            if user_id:
                QMessageBox.information(self, "Success", f"User '{name}' registered successfully!")
                self.face_processor.load_known_faces() # Reload known faces in the main app
                self.user_registered.emit() # Notify main window
                self.accept() # Close the dialog successfully
            else:
                QMessageBox.critical(self, "Database Error", f"Failed to save user '{name}' to the database.")
        else:
             logger.info("User save cancelled by user.")


    def closeEvent(self, event):
        """Ensure camera thread is stopped when dialog closes."""
        logger.debug("RegistrationDialog closeEvent triggered.")
        self._stop_registration_camera()
        super().closeEvent(event)

    # Make reject also stop the camera cleanly
    def reject(self):
        logger.debug("RegistrationDialog reject triggered.")
        self._stop_registration_camera()
        super().reject()