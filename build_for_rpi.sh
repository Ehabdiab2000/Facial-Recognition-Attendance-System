#!/bin/bash
# Build script for Raspberry Pi (Raspbian OS)
# Usage: bash build_for_rpi.sh

set -e

# Install dependencies
sudo apt-get update
sudo apt-get install -y python3-pyqt6 python3-opencv python3-pip python3-dev libatlas-base-dev libjasper-dev libqt6gui6 libqt6core6 libqt6widgets6

# Install Python requirements
pip3 install --upgrade pip
pip3 install -r requirements.txt

# Install PyInstaller if not present
pip3 install pyinstaller

# Build the executable
pyinstaller --onefile --noconfirm --name facial_attendance main.py

# Output location
if [ -f dist/facial_attendance ]; then
    echo "Build successful! Executable is in dist/facial_attendance"
else
    echo "Build failed. Check the output above for errors."
    exit 1
fi