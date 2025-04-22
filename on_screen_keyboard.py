# on_screen_keyboard.py
from PyQt6.QtWidgets import (QWidget, QPushButton, QGridLayout, QSizePolicy, 
                            QApplication, QLineEdit, QTabWidget, QVBoxLayout)
from PyQt6.QtCore import pyqtSignal, Qt

class OnScreenKeyboard(QWidget):
    key_pressed = pyqtSignal(str)
    enter_pressed = pyqtSignal()
    backspace_pressed = pyqtSignal()

    def __init__(self, target_lineEdit: QLineEdit = None, parent=None):
        super().__init__(parent)
        self.target_lineEdit = target_lineEdit
        self.is_shift = False
        self.initUI()

    def initUI(self):
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)
        
        # Set fixed width for RPi screen (600px)
        self.setFixedWidth(500)
        
        # Create tab widget for different keyboard pages
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        # Create keyboard pages
        self.letters_page = QWidget()
        self.numbers_page = QWidget()
        self.symbols_page = QWidget()
        
        self.tabs.addTab(self.letters_page, "Letters")
        self.tabs.addTab(self.numbers_page, "Numbers")
        self.tabs.addTab(self.symbols_page, "Symbols")
        
        # Setup each keyboard page
        self._setup_letters_page()
        self._setup_numbers_page()
        self._setup_symbols_page()

        self.is_shift = False
        self.update_keys() # Set initial case

    def _on_key_press(self, key):
        char_to_insert = key.upper() if self.is_shift else key.lower()
        self.key_pressed.emit(char_to_insert)
        if self.target_lineEdit:
            self.target_lineEdit.insert(char_to_insert)
        # Auto-unshift after typing a character (except for space)
        if self.is_shift and key != ' ':
            self.is_shift = False
            self.update_keys()

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
            elif key == 'SHIFT': # Handle shift button appearance
                button.setChecked(self.is_shift)


    def _setup_letters_page(self):
        """Setup the letters keyboard page."""
        grid = QGridLayout()
        self.letters_page.setLayout(grid)
        
        # Letters keyboard layout
        keys = [
            ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
            ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'],
            ['SHIFT', 'z', 'x', 'c', 'v', 'b', 'n', 'm', '<-'],
            ['SPACE', 'ENTER']
        ]
        
        self._add_keys_to_grid(grid, keys)
    
    def _setup_numbers_page(self):
        """Setup the numbers keyboard page."""
        grid = QGridLayout()
        self.numbers_page.setLayout(grid)
        
        # Numbers keyboard layout
        keys = [
            ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
            ['-', '/', ':', ';', '(', ')', '$', '&', '@', '"'],
            ['.', ',', '?', '!', '\'', '<-'],
            ['SPACE', 'ENTER']
        ]
        
        self._add_keys_to_grid(grid, keys)
    
    def _setup_symbols_page(self):
        """Setup the symbols keyboard page."""
        grid = QGridLayout()
        self.symbols_page.setLayout(grid)
        
        # Symbols keyboard layout
        keys = [
            ['[', ']', '{', '}', '#', '%', '^', '*', '+', '='],
            ['_', '\\', '|', '~', '<', '>', '€', '£', '¥', '•'],
            ['.', ',', '?', '!', '\'', '<-'],
            ['SPACE', 'ENTER']
        ]
        
        self._add_keys_to_grid(grid, keys)
    
    def _add_keys_to_grid(self, grid, keys):
        """Helper method to add keys to a grid layout."""
        for r, row_keys in enumerate(keys):
            for c, key in enumerate(row_keys):
                button = QPushButton(key)
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                
                if key == '<-':
                    button.clicked.connect(self._on_backspace)
                elif key == 'ENTER':
                    button.clicked.connect(self._on_enter)
                    grid.addWidget(button, r, c, 1, 4)
                elif key == 'SPACE':
                    button = QPushButton(" ")
                    button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                    button.clicked.connect(lambda _, k=" ": self._on_key_press(k))
                    grid.addWidget(button, r, c, 1, 8)
                    break
                elif key == 'SHIFT':
                    button.setCheckable(True)
                    button.clicked.connect(self._on_shift)
                    grid.addWidget(button, r, c)
                else:
                    button.clicked.connect(lambda _, k=key: self._on_key_press(k))
                    grid.addWidget(button, r, c)
    
    def set_target_lineEdit(self, lineEdit):
        """Set or change the target QLineEdit."""
        self.target_lineEdit = lineEdit

# Example usage (for testing the keyboard standalone)
if __name__ == '__main__':
    import sys
    app = QApplication(sys.argv)
    window = QWidget()
    layout = QVBoxLayout(window)
    lineEdit = QLineEdit()
    keyboard = OnScreenKeyboard(lineEdit)
    layout.addWidget(lineEdit)
    layout.addWidget(keyboard)
    window.setWindowTitle("On-Screen Keyboard Test")
    window.show()
    sys.exit(app.exec())