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
from PyQt6.QtCore import pyqtSlot

# Assuming face_processor handles encoding generation
from face_processor import FaceProcessor
from on_screen_keyboard import OnScreenKeyboard
from camera_thread import CameraThread # To get camera feed

logger = logging.getLogger(__name__)

class RegistrationDialog(QDialog):
    user_registered = pyqtSignal() # Signal emitted when user is successfully registered

    def __init__(self, db_manager, face_processor: FaceProcessor, parent=None, edit_user_id=None, wiegand_reader_instance=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.face_processor = face_processor
        self.wiegand_reader_instance = wiegand_reader_instance
        self.setWindowTitle("Register New User" if edit_user_id is None else "Edit User")
        self.setModal(True) # Block main window interaction

        # State variables
        self.current_frame = None
        self.captured_encoding = None
        self.face_location = None # Store location of the face used for encoding
        self.edit_user_id = edit_user_id # Track if we're editing an existing user
        self.original_card_number = None # To check if card number changed during edit

        # UI Elements
        self._setup_ui() # Call before loading data if editing

        if self.edit_user_id:
            self.load_user_data_for_editing()

        # If Wiegand reader is passed, connect its signal to populate the card field
        if self.wiegand_reader_instance:
            try:
                self.wiegand_reader_instance.card_scanned.connect(self.on_card_scanned_in_dialog)
            except Exception as e:
                logger.error(f"Error connecting Wiegand signal in RegistrationDialog: {e}")


        # On-Screen Keyboard
        self.keyboard = OnScreenKeyboard()
        self.main_layout.addWidget(self.keyboard) # Add keyboard to layout

        # Connect keyboard focus
        self.name_input.installEventFilter(self)
        self.details_input.installEventFilter(self)
        self.card_input.installEventFilter(self) # Add card_input to event filter
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

        self.setMinimumSize(500, 800) # Adjust size as needed

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

        # --- Add Card Number Field ---
        self.card_label = QLabel("Card Number:")
        self.card_input = QLineEdit()
        self.card_input.setPlaceholderText("Enter or scan card number")
        input_layout.addWidget(self.card_label)
        input_layout.addWidget(self.card_input)
        # -----------------------------

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
        self.save_button = QPushButton("Save User" if self.edit_user_id is None else "Update User")
        # Enable save button if editing existing user, or if face captured for new
        if self.edit_user_id:
            self.save_button.setEnabled(True)
        else:
            self.save_button.setEnabled(False) # Only enable after face capture for new user
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
            elif source is self.card_input: # Add card_input to keyboard target
                self.keyboard.set_target_lineEdit(self.card_input)
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
        # If capturing a face for a new user, save button is enabled
        if self.captured_encoding is not None and self.edit_user_id is None:
            self.save_button.setEnabled(True)
        elif self.edit_user_id is not None: # If editing, save is already enabled, capture is optional
             self.save_button.setEnabled(True) # Ensure it stays enabled
        logger.info("Face encoding captured successfully for registration.")

        # Update preview immediately to show the captured face box
        self._update_preview_frame(self.current_frame, config.PRIMARY_CAMERA_INDEX)


    def load_user_data_for_editing(self):
        if self.edit_user_id is None:
            return
        user_data = self.db_manager.get_user_by_id(self.edit_user_id)
        if user_data:
            self.name_input.setText(user_data['name'])
            self.details_input.setText(user_data['details'] or "")
            self.card_input.setText(user_data['card_number'] or "")
            self.original_card_number = user_data['card_number'] # Store for checking changes
            # Note: Face encoding is not pre-loaded; user must re-capture if they want to change it.
            self.status_label.setText("Editing user. Capture new face to update or save existing details.")
        else:
            QMessageBox.critical(self, "Error", f"Could not load data for user ID {self.edit_user_id}.")
            self.reject() # Close if user not found

    @pyqtSlot(str) # Slot to receive card number
    def on_card_scanned_in_dialog(self, card_number):
        # This slot is active only when the dialog is open
        if self.isVisible(): # Check if dialog is currently visible
            logger.info(f"Card scanned in registration dialog: {card_number}")
            self.card_input.setText(card_number)
            # Optionally, provide feedback to the user
            # QMessageBox.information(self, "Card Scanned", f"Card Number: {card_number} captured.")

    def save_user(self):
        """Validates input and saves the user to the database."""
        name = self.name_input.text().strip()
        details = self.details_input.text().strip()
        card_number = self.card_input.text().strip() # Get card number

        if not name:
            QMessageBox.warning(self, "Input Error", "Name cannot be empty.")
            return

        # If new user, face encoding is mandatory
        if self.edit_user_id is None and self.captured_encoding is None:
            QMessageBox.warning(self, "Input Error", "No face encoding has been captured for new user.")
            return

        action = "update" if self.edit_user_id else "register"
        confirm_msg = f"{action.capitalize()} user '{name}'?"
        if self.captured_encoding is not None and self.captured_encoding.any():
            confirm_msg += " (Face will be updated/set)"
        if card_number:
            confirm_msg += f" (Card: {card_number})"
        elif self.edit_user_id and self.original_card_number and not card_number:
             confirm_msg += f" (Card will be REMOVED)"


        reply = QMessageBox.question(self, 'Confirm Save', confirm_msg,
                                       QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Save:
            success = False
            if self.edit_user_id:
                # Update existing user
                # Pass card_number to update_user_details
                success = self.db_manager.update_user_details(self.edit_user_id, name, details, card_number)
                if self.captured_encoding is not None: # Only update encoding if a new one was captured
                    encoding_success = self.db_manager.update_user_encoding(self.edit_user_id, self.captured_encoding)
                    success = success and encoding_success # Combine success flags
                if success:
                    QMessageBox.information(self, "Success", f"User '{name}' updated successfully!")
                else:
                    # Check if it was a card number conflict
                    # This requires db_manager.update_user_details to indicate this specific error
                    # For now, a generic message or check self.db_manager for last error if possible
                    QMessageBox.critical(self, "Database Error", f"Failed to update user '{name}'. Card number might be in use by another user, or another error occurred.")
            else: # Add new user
                # Pass card_number to add_user
                user_id = self.db_manager.add_user(name, details, self.captured_encoding, card_number)
                if user_id:
                    success = True
                    QMessageBox.information(self, "Success", f"User '{name}' registered successfully!")
                else:
                    QMessageBox.critical(self, "Database Error", f"Failed to save user '{name}'. Card number might already exist or another error occurred.")

            if success:
                self.face_processor.load_known_faces() # Reload known faces for main app
                self.user_registered.emit() # Signal that a user was added/updated
                self.accept() # Close dialog
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
        # Disconnect Wiegand reader signal if connected
        if self.wiegand_reader_instance:
            try:
                self.wiegand_reader_instance.card_scanned.disconnect(self.on_card_scanned_in_dialog)
            except TypeError: # Raised if not connected or already disconnected
                logger.debug("Wiegand signal already disconnected or was not connected in reject.")
            except Exception as e:
                logger.error(f"Error disconnecting Wiegand signal in reject: {e}")
        super().reject()