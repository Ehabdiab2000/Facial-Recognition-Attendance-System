# user_management_dialog.py
import cv2
import numpy as np
import config
import logging
import face_recognition
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QWidget, QApplication, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QDialogButtonBox
)
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

from face_processor import FaceProcessor
from database_manager import DatabaseManager
from camera_thread import CameraThread
from on_screen_keyboard import OnScreenKeyboard # Re-add keyboard if needed for editing

logger = logging.getLogger(__name__)

class UserManagementDialog(QDialog):
    users_changed = pyqtSignal() # Signal emitted when users are added, modified, or deleted

    def __init__(self, db_manager: DatabaseManager, face_processor: FaceProcessor, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.face_processor = face_processor
        self.setWindowTitle("User Management")
        self.setModal(True)
        self.setMinimumSize(500, 800)

        # State variables for potential editing/adding
        self.current_frame = None
        self.captured_encoding = None
        self.face_location = None
        self.editing_user_id = None # Track which user is being edited
        self.reg_camera_thread = None

        self._setup_ui()
        self.populate_user_table()

    def _setup_ui(self):
        self.main_layout = QVBoxLayout(self)

        # User Table
        self.user_table = QTableWidget()
        self.user_table.setColumnCount(4) # ID, Name, Details, Actions
        self.user_table.setHorizontalHeaderLabels(["ID", "Name", "Details", "Actions"])
        self.user_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.user_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers) # Don't allow direct editing in table
        self.user_table.verticalHeader().setVisible(False)
        header = self.user_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) # ID
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)         # Name
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)         # Details
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents) # Actions
        self.main_layout.addWidget(self.user_table)

        # Action Buttons (Add, Close)
        button_layout = QHBoxLayout()
        self.add_user_button = QPushButton("Add New User")
        self.add_user_button.clicked.connect(self.open_add_user_dialog) # Separate dialog for adding
        button_layout.addWidget(self.add_user_button)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.accept) # Close the management dialog
        button_layout.addWidget(self.close_button)

        self.main_layout.addLayout(button_layout)

    def populate_user_table(self):
        self.user_table.setRowCount(0) # Clear existing rows
        try:
            users = self.db_manager.get_all_users()
            if not users:
                logger.info("No users found in the database.")
                # Optionally display a message in the table
                self.user_table.setRowCount(1)
                no_user_item = QTableWidgetItem("No users registered yet.")
                no_user_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.user_table.setItem(0, 0, no_user_item)
                self.user_table.setSpan(0, 0, 1, self.user_table.columnCount())
                return

            self.user_table.setRowCount(len(users))
            for row, user in enumerate(users):
                user_id, name, details, _, _ = user # Encoding and card_number not needed here

                # Create items
                id_item = QTableWidgetItem(str(user_id))
                id_item.setData(Qt.ItemDataRole.UserRole, user_id) # Store ID for later use
                name_item = QTableWidgetItem(name)
                details_item = QTableWidgetItem(details if details else "-")

                # Make items non-editable visually
                id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                details_item.setFlags(details_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                # Set items in table
                self.user_table.setItem(row, 0, id_item)
                self.user_table.setItem(row, 1, name_item)
                self.user_table.setItem(row, 2, details_item)

                # Action buttons (Edit, Delete)
                action_widget = QWidget()
                action_layout = QHBoxLayout(action_widget)
                action_layout.setContentsMargins(0, 0, 0, 0)
                action_layout.setSpacing(5)

                edit_button = QPushButton("Edit")
                edit_button.setProperty("user_id", user_id) # Store user_id in button property
                edit_button.clicked.connect(self.open_edit_user_dialog)
                action_layout.addWidget(edit_button)

                delete_button = QPushButton("Delete")
                delete_button.setProperty("user_id", user_id)
                delete_button.setProperty("user_name", name)
                delete_button.clicked.connect(self.delete_user)
                action_layout.addWidget(delete_button)

                action_layout.addStretch()
                self.user_table.setCellWidget(row, 3, action_widget)

        except Exception as e:
            logger.error(f"Error populating user table: {e}", exc_info=True)
            QMessageBox.critical(self, "Database Error", f"Failed to load users: {e}")

    def open_add_user_dialog(self):
        logger.info("Opening Add User dialog.")
        # Use a separate dialog, similar to the original RegistrationDialog but simplified
        # Or reuse RegistrationDialog if it fits the purpose
        # For now, let's assume a dedicated AddUserDialog or reuse RegistrationDialog
        from registration_dialog import RegistrationDialog # Reuse for simplicity
        add_dialog = RegistrationDialog(self.db_manager, self.face_processor, self)
        add_dialog.setWindowTitle("Add New User")
        add_dialog.user_registered.connect(self._handle_user_change) # Connect signal
        add_dialog.exec()

    def open_edit_user_dialog(self):
        sender_button = self.sender()
        if not sender_button:
            return
        user_id = sender_button.property("user_id")
        if user_id is None:
            logger.warning("Edit button clicked but user_id not found.")
            return

        logger.info(f"Opening Edit User dialog for user ID: {user_id}")
        # Reuse RegistrationDialog for editing
        from registration_dialog import RegistrationDialog
        edit_dialog = RegistrationDialog(self.db_manager, self.face_processor, self, edit_user_id=user_id)
        
        # Pre-fill existing user data
        user_data = self.db_manager.get_user_by_id(user_id)
        if not user_data:
            QMessageBox.warning(self, "Error", f"Could not find user with ID {user_id}.")
            return
            
        _, name, details, _ = user_data
        edit_dialog.name_input.setText(name)
        edit_dialog.details_input.setText(details if details else "")
        
        edit_dialog.user_registered.connect(self._handle_user_change)
        edit_dialog.exec()

    def _save_user_edits(self, user_id, new_name, new_details, dialog):
        new_name = new_name.strip()
        new_details = new_details.strip()
        if not new_name:
            QMessageBox.warning(dialog, "Input Error", "Name cannot be empty.")
            return

        # Here you would add logic to update face encoding if re-capture was implemented
        # For now, just update name and details
        success = self.db_manager.update_user_details(user_id, new_name, new_details)
        if success:
            QMessageBox.information(dialog, "Success", "User details updated.")
            self._handle_user_change() # Signal change and refresh table
            dialog.accept()
        else:
            QMessageBox.critical(dialog, "Database Error", "Failed to update user details.")

    def delete_user(self):
        sender_button = self.sender()
        if not sender_button:
            return
        user_id = sender_button.property("user_id")
        user_name = sender_button.property("user_name")
        if user_id is None:
            logger.warning("Delete button clicked but user_id not found.")
            return

        reply = QMessageBox.question(self, 'Confirm Delete',
                                       f"Are you sure you want to delete user '{user_name}' (ID: {user_id})?\nThis action cannot be undone.",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            logger.info(f"Attempting to delete user ID: {user_id}")
            success = self.db_manager.delete_user(user_id)
            if success:
                QMessageBox.information(self, "Success", f"User '{user_name}' deleted successfully.")
                self._handle_user_change() # Signal change and refresh table
            else:
                QMessageBox.critical(self, "Database Error", f"Failed to delete user '{user_name}'.")
        else:
            logger.info(f"Deletion cancelled for user ID: {user_id}")

    def _handle_user_change(self):
        """Called when a user is added, edited, or deleted."""
        self.populate_user_table() # Refresh the table
        self.users_changed.emit()  # Emit signal for main window

    def closeEvent(self, event):
        """Ensure camera thread is stopped if it was started for editing."""
        self._stop_edit_camera() # Implement this if camera is used
        super().closeEvent(event)

    def reject(self):
        """Ensure camera thread is stopped if it was started for editing."""
        self._stop_edit_camera() # Implement this if camera is used
        super().reject()

    # Placeholder for camera stop function if needed for editing
    def _stop_edit_camera(self):
        if self.reg_camera_thread and self.reg_camera_thread.isRunning():
            logger.info("Stopping User Management edit camera thread.")
            self.reg_camera_thread.stop()
            self.reg_camera_thread = None

# Example of how to start camera if needed for editing (not fully implemented above)
# def _start_edit_camera(self):
#     if self.reg_camera_thread is None or not self.reg_camera_thread.isRunning():
#          self.reg_camera_thread = CameraThread(config.PRIMARY_CAMERA_INDEX, target_fps=10)
#          # Connect signals to appropriate slots in the edit dialog
#          # self.reg_camera_thread.frame_ready.connect(self._update_edit_preview_frame)
#          # self.reg_camera_thread.error.connect(self._handle_edit_camera_error)
#          self.reg_camera_thread.start()
#          logger.info("Edit camera thread started.")