# Facial Recognition Attendance System with Anti-Spoofing

[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A facial recognition-based attendance system designed for Raspberry Pi 4, utilizing PyQt6 for the user interface, OpenCV for camera interaction, and the `face_recognition` library for identification. It features basic liveness detection (anti-spoofing) using blink detection, user registration with an on-screen keyboard, local data storage with offline buffering, and hardware integration for door access control (relay) and status indication (LEDs).

## Key Features

*   **Facial Recognition:** Identifies registered users via webcam feed.
*   **User Registration:** A dedicated interface to register new users, capture their face encoding, and enter details using an on-screen keyboard.
*   **Local Database:** Uses SQLite to store user information (including face encodings) and attendance transaction logs.
*   **Offline Capability:** Logs attendance locally and syncs with a central attendance server (`your_attendance_server.com`) when network connectivity is available.
*   **Hardware Integration:**
    *   Controls a relay connected to GPIO pins to open a door upon successful identification.
    *   Manages Red/Green LEDs via GPIO to indicate system status and identification results.
*   **Basic Liveness Detection:** Implements blink detection using eye aspect ratio calculation to mitigate simple spoofing attempts (e.g., using static photos). **Note:** This is a basic implementation and may not stop sophisticated attacks.
*   **Cross-Platform Testing:** Includes a configuration flag (`USE_GPIO`) to disable hardware interactions, allowing testing and development on non-Raspberry Pi systems (like a laptop).
*   **GUI:** User-friendly interface built with PyQt6.
*   **Configuration:** Key parameters (camera indices, GPIO pins, server URL, thresholds) are managed in `config.py`.

## Hardware Requirements

*   **Primary:** Raspberry Pi 4 Model B (2GB RAM or more recommended)
*   **Testing/Development:** Laptop or Desktop PC (Linux, macOS, Windows)
*   **Cameras:**
    *   1 or 2 USB Webcams (Tested with 1 primary camera for recognition and liveness. The second camera index is configurable but currently not utilized beyond potential future use).
*   **Display:** Monitor compatible with Raspberry Pi (HDMI). A touchscreen is recommended for easier interaction with the on-screen keyboard.
*   **Input:** USB Mouse/Keyboard (if not using a touchscreen).
*   **Hardware Control (Raspberry Pi Only):**
    *   5V Relay Module (compatible with Raspberry Pi GPIO levels)
    *   LEDs (1x Red, 1x Green)
    *   Resistors for LEDs (e.g., 220-330 Ohm, depending on LED specs)
    *   Jumper Wires
    *   Breadboard (Optional, for easier connections)

## Software Requirements

*   **Operating System:**
    *   Raspberry Pi OS (Legacy/Buster or newer, 32-bit or 64-bit)
    *   Linux / macOS / Windows (for testing/development)
*   **Python:** 3.8 or higher
*   **Core Libraries:** See `requirements.txt`. Key libraries include:
    *   `PyQt6`
    *   `opencv-python`
    *   `face_recognition` (which depends on `dlib`)
    *   `numpy`
    *   `requests`
    *   `RPi.GPIO` (Raspberry Pi only)
*   **`dlib` Dependencies (Crucial for Linux/Raspberry Pi):**
    *   `build-essential`, `cmake`
    *   `libopenblas-dev`, `liblapack-dev`
    *   `libx11-dev`, `libgtk-3-dev` (for GUI features within dlib, though maybe less critical here)
    *   `python3-dev`

## Installation

1.  **Clone the Repository:**
    ```bash
    git clone <your-repository-url>
    cd <repository-directory>
    ```

2.  **Install System Dependencies (Raspberry Pi / Linux):**
    *   Update package list:
        ```bash
        sudo apt-get update
        ```
    *   Install build tools and libraries required for `dlib` and `OpenCV`:
        ```bash
        sudo apt-get install build-essential cmake pkg-config -y
        sudo apt-get install libopenblas-dev liblapack-dev -y
        sudo apt-get install libjpeg-dev libpng-dev libtiff-dev -y # Image I/O
        sudo apt-get install libavcodec-dev libavformat-dev libswscale-dev libv4l-dev -y # Video I/O
        sudo apt-get install libxvidcore-dev libx264-dev -y
        sudo apt-get install libgtk-3-dev -y # GUI backend for OpenCV/dlib
        sudo apt-get install python3-dev -y
        # Optional but recommended for performance
        sudo apt-get install libatlas-base-dev gfortran -y
        ```
    *   *(macOS/Windows): You might need different steps, potentially using `brew` or installing pre-built binaries/wheels.*

3.  **Create and Activate a Virtual Environment (Recommended):**
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Linux/macOS
    # venv\Scripts\activate  # On Windows
    ```

4.  **Install Python Packages:**
    *   Upgrade pip:
        ```bash
        pip install --upgrade pip
        ```
    *   Install requirements:
        ```bash
        pip install -r requirements.txt
        ```
        *Note: `dlib` installation can take a significant amount of time as it often compiles from source.* If you encounter issues, search for specific errors related to your OS and Python version. Pre-compiled wheels might be available for some platforms.

## Hardware Setup (Raspberry Pi)

**⚠️ Warning:** Incorrect wiring can damage your Raspberry Pi or connected components. Proceed with caution and double-check connections. Refer to your specific relay module's documentation.

1.  **Connect Relay:**
    *   Connect the relay module's VCC to a 5V pin on the Pi.
    *   Connect the relay module's GND to a GND pin on the Pi.
    *   Connect the relay module's IN (Input) pin to the GPIO pin specified by `RELAY_PIN` in `config.py` (default: GPIO 17 / Pin 11).
    *   Connect your door lock mechanism to the relay's output terminals (NO/NC - Normally Open / Normally Closed, depending on your lock type) according to the lock and relay documentation.
2.  **Connect LEDs:**
    *   **Green LED:** Connect the longer leg (anode) to the GPIO pin specified by `GREEN_LED_PIN` in `config.py` (default: GPIO 27 / Pin 13) via a current-limiting resistor (e.g., 330Ω). Connect the shorter leg (cathode) to a GND pin.
    *   **Red LED:** Connect the longer leg (anode) to the GPIO pin specified by `RED_LED_PIN` in `config.py` (default: GPIO 22 / Pin 15) via a current-limiting resistor. Connect the shorter leg (cathode) to a GND pin.

## Configuration (`config.py`)

Before running, review and adjust `config.py`:

*   `PRIMARY_CAMERA_INDEX`: Set to `0`, `1`, etc., based on your primary camera detected by the OS (`ls /dev/video*` on Linux).
*   `SECONDARY_CAMERA_INDEX`: Set to the index of the second camera, or `None` if only using one.
*   `USE_GPIO`: Set to `True` when running on Raspberry Pi with hardware connected. Set to `False` for testing on a laptop/PC without GPIO.
*   `RELAY_PIN`, `GREEN_LED_PIN`, `RED_LED_PIN`: Ensure these match the GPIO pins (BCM numbering) you used for wiring.
*   `SERVER_URL`: **Crucially, change this** to the actual endpoint URL of your backend attendance server API. The API should expect a POST request with JSON data like `{'user_id': ..., 'user_name': ..., 'timestamp': ..., 'local_transaction_id': ...}`.
*   `RECOGNITION_THRESHOLD`: Adjust face matching strictness (lower is stricter, default 0.55 is reasonable).
*   Other parameters: Frame dimensions, FPS limits, timeouts, etc.

## Running the Application

1.  **Activate Virtual Environment:**
    ```bash
    source venv/bin/activate # Or Windows equivalent
    ```
2.  **Run the Main Script:**
    ```bash
    python main.py
    ```
    *   On Raspberry Pi, if you encounter GPIO permission errors, you might need to run with `sudo`:
        ```bash
        sudo python main.py
        ```
        (A better long-term solution is to add your user to the `gpio` group: `sudo adduser $USER gpio` and reboot).

## Usage

1.  **Main Screen:** The application will start, showing the camera feed. The status bar at the bottom displays messages and system status. LEDs will indicate status (Red default, Green on identification).
2.  **Registration:**
    *   Click the "Register New User" button.
    *   A dialog window appears with a camera preview.
    *   Enter the user's name and optional details using the on-screen keyboard.
    *   Position the user's face clearly in the preview and click "Capture Face". Ensure only one face is clearly visible. The system selects the largest face if multiple are detected.
    *   If successful, the status will indicate capture success, and the "Save User" button will be enabled.
    *   Click "Save User" to store the information.
    *   The dialog closes, and the system returns to the main screen.
3.  **Attendance:**
    *   Registered users simply need to look at the camera.
    *   If a known face is detected and the liveness check (blink) passes within the cooldown period, the system will:
        *   Display a welcome message.
        *   Turn the LED Green.
        *   Activate the relay briefly to open the door.
        *   Log the transaction locally.
        *   Queue the transaction for sending to the server.
    *   Unknown faces or failed liveness checks will result in appropriate status messages and the LED remaining/turning Red.

## Liveness Detection Note

The current anti-spoofing mechanism relies on blink detection (checking the Eye Aspect Ratio). This can prevent basic attacks using static photos but is **not foolproof** against video replays or more sophisticated masks/presentation attacks. For higher security requirements, consider integrating more advanced liveness detection models or hardware (e.g., IR or 3D cameras).

## Troubleshooting

*   **Camera Not Found/Working:**
    *   Check connections.
    *   Verify camera index in `config.py` using `ls /dev/video*`.
    *   Ensure OpenCV can access the camera (permissions, drivers).
*   **`dlib` Installation Errors:** Carefully check the system dependencies installation steps. Search online for specific compilation errors related to your OS/Python version. Using a virtual environment is highly recommended to avoid conflicts.
*   **GPIO Errors (Permission Denied):** Run with `sudo` or add your user to the `gpio` group.
*   **Slow Performance on Raspberry Pi:**
    *   Ensure you are using a Pi 4.
    *   Lower `FRAME_WIDTH`, `FRAME_HEIGHT`, and `FPS_LIMIT` in `config.py`.
    *   The `face_recognition` library can be CPU-intensive. Consider exploring OpenCV's DNN module with optimized models (like YuNet for detection, MobileFaceNet for recognition) for better performance if needed.
    *   Close unnecessary background applications on the Pi.

## TODO / Future Improvements

*   [ ] Implement more robust Liveness Detection (e.g., pre-trained models).
*   [ ] Optimize performance further for Raspberry Pi (OpenCV DNN, model quantization).
*   [ ] Add configuration loading from a file (JSON/YAML).
*   [ ] Improve UI/UX (Qt Designer, better layout, icons).
*   [ ] Enhance error handling and reporting.
*   [ ] Add functionality to view/manage users and transactions directly from the UI.
*   [ ] Implement proper use of the secondary camera (e.g., PiP display, stereo liveness).
*   [ ] Add automated setup script.
*   [ ] Implement unit and integration tests.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file (if you create one) for details.

## Acknowledgements

*   `face_recognition` library by Adam Geitgey
*   OpenCV library
*   PyQt6 framework
*   `dlib` library
