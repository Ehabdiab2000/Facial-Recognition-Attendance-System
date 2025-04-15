# on_screen_keyboard.py
from PyQt6.QtWidgets import QWidget, QPushButton, QGridLayout, QSizePolicy, QApplication, QLineEdit
from PyQt6.QtCore import pyqtSignal, Qt

class OnScreenKeyboard(QWidget):
    key_pressed = pyqtSignal(str)
    enter_pressed = pyqtSignal()
    backspace_pressed = pyqtSignal()

    def __init__(self, target_lineEdit: QLineEdit = None, parent=None):
        super().__init__(parent)
        self.target_lineEdit = target_lineEdit
        self.initUI()

    def initUI(self):
        grid = QGridLayout()
        self.setLayout(grid)

        # Define keyboard layout (simple example)
        keys = [
            ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '<-'], # Row 1
            ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],      # Row 2
            ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', ';'],      # Row 3
            ['SHIFT','z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.'],        # Row 4
             ['SPACE', 'ENTER']                                       # Row 5 (Spanning)
        ]

        self.is_shift = False

        for r, row_keys in enumerate(keys):
            for c, key in enumerate(row_keys):
                button = QPushButton(key)
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus) # Prevent keyboard from taking focus

                if key == '<-':
                    button.clicked.connect(self._on_backspace)
                elif key == 'ENTER':
                    button.clicked.connect(self._on_enter)
                    grid.addWidget(button, r, c, 1, 4) # Span ENTER button
                elif key == 'SPACE':
                     button = QPushButton(" ") # Display space
                     button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                     button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                     button.clicked.connect(lambda _, k=" ": self._on_key_press(k))
                     grid.addWidget(button, r, c, 1, 8) # Span SPACE button
                     break # Skip rest of row after space
                elif key == 'SHIFT':
                     button.setCheckable(True)
                     button.clicked.connect(self._on_shift)
                     grid.addWidget(button, r, c)
                else:
                    button.clicked.connect(lambda _, k=key: self._on_key_press(k))
                    grid.addWidget(button, r, c)

        self.update_keys() # Set initial case

    def _on_key_press(self, key):
        char_to_insert = key.upper() if self.is_shift else key.lower()
        self.key_pressed.emit(char_to_insert)
        if self.target_lineEdit:
            self.target_lineEdit.insert(char_to_insert)
        # Un-toggle shift after typing a letter if it's toggled
        # if self.is_shift:
        #    self.is_shift = False
        #    self.update_keys() # Consider this behavior - maybe caps lock is better?

    def _on_backspace(self):
        self.backspace_pressed.emit()
        if self.target_lineEdit:
            self.target_lineEdit.backspace()

    def _on_enter(self):
        self.enter_pressed.emit()
        # Optionally hide keyboard or trigger action in parent dialog

    def _on_shift(self, checked):
         self.is_shift = checked
         self.update_keys()


    def update_keys(self):
        """Update button text based on shift state."""
        for button in self.findChildren(QPushButton):
             key = button.text()
             if len(key) == 1 and key.isalpha(): # Only affect letters
                 button.setText(key.upper() if self.is_shift else key.lower())
             elif key == ' ': # Handle spacebar text if needed
                  pass
             elif key == 'Shift': # Handle shift button appearance
                  button.setChecked(self.is_shift)


    def set_target_lineEdit(self, lineEdit):
        """Set or change the target QLineEdit."""
        self.target_lineEdit = lineEdit

# Example usage (for testing the keyboard standalone)
if __name__ == '__main__':
    import sys
    app = QApplication(sys.argv)
    window = QWidget()
    layout = QGridLayout(window)
    lineEdit = QLineEdit()
    keyboard = OnScreenKeyboard(lineEdit)
    layout.addWidget(lineEdit, 0, 0)
    layout.addWidget(keyboard, 1, 0)
    window.setWindowTitle("On-Screen Keyboard Test")
    window.show()
    sys.exit(app.exec())