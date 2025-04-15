# camera_thread.py
import cv2
import time
import logging
from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker

logger = logging.getLogger(__name__)

class CameraThread(QThread):
    # Signals emitting the raw frame and processed frame info
    frame_ready = pyqtSignal(object, int) # Emits the captured frame (numpy array) and camera index
    error = pyqtSignal(str, int)       # Emits error message and camera index

    def __init__(self, camera_index, target_fps=15, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self.target_fps = target_fps
        self.interval = 1.0 / self.target_fps if self.target_fps > 0 else 0
        self._running = False
        self._capture = None
        self._mutex = QMutex() # To protect access to self._running

    def run(self):
        logger.info(f"Camera thread {self.camera_index} starting.")
        with QMutexLocker(self._mutex):
            self._running = True

        try:
            self._capture = cv2.VideoCapture(self.camera_index)
            if not self._capture.isOpened():
                raise IOError(f"Cannot open camera {self.camera_index}")

            logger.info(f"Camera {self.camera_index} opened successfully.")

            while True:
                with QMutexLocker(self._mutex):
                    if not self._running:
                        break # Exit loop if stopped

                start_time = time.time()

                ret, frame = self._capture.read()
                if not ret:
                    logger.warning(f"Failed to grab frame from camera {self.camera_index}. Retrying...")
                    time.sleep(0.5) # Wait a bit before retrying
                    # Attempt to reopen camera if fails consistently
                    self._capture.release()
                    self._capture = cv2.VideoCapture(self.camera_index)
                    if not self._capture.isOpened():
                         logger.error(f"Failed to reopen camera {self.camera_index}. Stopping thread.")
                         self.error.emit(f"Failed to reopen camera {self.camera_index}", self.camera_index)
                         break # Exit loop permanently if reopen fails
                    continue # Skip this frame


                # Emit the raw frame
                if frame is not None:
                    self.frame_ready.emit(frame.copy(), self.camera_index) # Emit a copy

                # Limit FPS
                elapsed_time = time.time() - start_time
                sleep_time = self.interval - elapsed_time
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except Exception as e:
            logger.error(f"Error in camera thread {self.camera_index}: {e}", exc_info=True)
            self.error.emit(str(e), self.camera_index)
        finally:
            if self._capture:
                self._capture.release()
                logger.info(f"Camera {self.camera_index} released.")
            with QMutexLocker(self._mutex):
                self._running = False
            logger.info(f"Camera thread {self.camera_index} finished.")


    def stop(self):
        logger.info(f"Attempting to stop camera thread {self.camera_index}...")
        with QMutexLocker(self._mutex):
            self._running = False
        self.wait(2000) # Wait up to 2 seconds for the thread to finish cleanly
        if self.isRunning():
             logger.warning(f"Camera thread {self.camera_index} did not stop gracefully. Terminating.")
             self.terminate() # Force terminate if it doesn't stop