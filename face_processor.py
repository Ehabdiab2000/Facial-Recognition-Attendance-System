# face_processor.py
import face_recognition
import numpy as np
import cv2
import config
import logging
from scipy.spatial import distance as dist

logger = logging.getLogger(__name__)

# --- Liveness Detection Helper ---
def eye_aspect_ratio(eye):
    # compute the euclidean distances between the two sets of
    # vertical eye landmarks (x, y)-coordinates
    A = dist.euclidean(eye[1], eye[5])
    B = dist.euclidean(eye[2], eye[4])
    # compute the euclidean distance between the horizontal
    # eye landmark (x, y)-coordinates
    C = dist.euclidean(eye[0], eye[3])
    # compute the eye aspect ratio
    ear = (A + B) / (2.0 * C)
    return ear

# Global state for blink detection per face (needs association if multiple faces)
# Simple version: Tracks blinks for the *primary* detected face
blink_counter = 0
eyes_closed_for_frames = 0
last_blink_check_frame = 0

# --- Face Processing Class ---
class FaceProcessor:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.known_face_encodings = []
        self.known_face_data = [] # Store {'id': id, 'name': name}
        self.load_known_faces()

    def load_known_faces(self):
        """Loads known face encodings and names from the database."""
        self.known_face_encodings = []
        self.known_face_data = []
        users = self.db_manager.get_all_users()
        if not users:
             logger.warning("No users found in the database.")
             return
        for user in users:
            try:
                encoding = user['encoding'] # Already converted by converter
                if encoding is not None and isinstance(encoding, np.ndarray):
                    self.known_face_encodings.append(encoding)
                    self.known_face_data.append({'id': user['id'], 'name': user['name']})
                else:
                    logger.warning(f"Invalid or missing encoding for user {user['name']} (ID: {user['id']}). Skipping.")
            except Exception as e:
                 logger.error(f"Error loading encoding for user {user['name']}: {e}")

        logger.info(f"Loaded {len(self.known_face_encodings)} known face encodings.")

    def detect_and_encode(self, frame_rgb):
        """Detects faces and computes encodings for a single frame."""
        # Find all face locations and face encodings in the current frame
        face_locations = face_recognition.face_locations(frame_rgb, model="hog") # "cnn" is more accurate but MUCH slower
        if not face_locations:
            return [], [], [] # No faces found

        face_encodings = face_recognition.face_encodings(frame_rgb, face_locations)
        face_landmarks = face_recognition.face_landmarks(frame_rgb, face_locations)

        return face_locations, face_encodings, face_landmarks

    def recognize_faces(self, face_encodings):
        """Compares detected encodings against known encodings."""
        recognized_faces = []
        if not self.known_face_encodings:
            # Return default unknown if no known faces exist
             return [{'id': None, 'name': config.UNKNOWN_PERSON_LABEL, 'distance': 1.0} for _ in face_encodings]


        for face_encoding in face_encodings:
            # Compare the current face encoding to all known face encodings
            matches = face_recognition.compare_faces(self.known_face_encodings, face_encoding, tolerance=config.RECOGNITION_THRESHOLD)
            face_distances = face_recognition.face_distance(self.known_face_encodings, face_encoding)

            best_match_index = -1
            min_distance = 1.0 # Max possible distance is theoretically sqrt(2) but usually lower

            if True in matches:
                # Find the index of the best match (lowest distance)
                best_match_index = np.argmin(face_distances)
                min_distance = face_distances[best_match_index]

                # Additional check: Ensure the best match is actually below the threshold
                if not matches[best_match_index]: # Should not happen if True in matches exists, but good sanity check
                   best_match_index = -1
                   min_distance = 1.0


            if best_match_index != -1:
                user_data = self.known_face_data[best_match_index]
                recognized_faces.append({
                    'id': user_data['id'],
                    'name': user_data['name'],
                    'distance': min_distance
                })
                logger.debug(f"Recognized {user_data['name']} with distance {min_distance:.2f}")
            else:
                recognized_faces.append({
                    'id': None,
                    'name': config.UNKNOWN_PERSON_LABEL,
                    'distance': np.min(face_distances) if len(face_distances) > 0 else 1.0 # Show distance to closest non-match
                })
                logger.debug(f"Detected face, but no match found (closest distance: {np.min(face_distances):.2f})")


        return recognized_faces

    def check_liveness_blink(self, landmarks_list, frame_count):
        """
        Basic blink detection for liveness. Assumes single primary face for simplicity.
        Returns True if a blink was detected recently, False otherwise.
        """
        global blink_counter, eyes_closed_for_frames, last_blink_check_frame

        # Only check periodically
        if frame_count < last_blink_check_frame + config.BLINK_DETECTION_INTERVAL_FRAMES:
             # Assume previous state holds or not enough data yet
            return blink_counter > 0 # Return True if a blink was detected in the recent past

        last_blink_check_frame = frame_count
        live = False # Default to not live unless blink detected

        if not landmarks_list: # No faces with landmarks
            eyes_closed_for_frames = 0 # Reset counter if no face
            # Keep blink_counter > 0 for a short while? Or reset immediately? Reset for now.
            # blink_counter = 0
            return blink_counter > 0

        # --- Focus on the first detected face's landmarks for simplicity ---
        landmarks = landmarks_list[0]
        left_eye = landmarks['left_eye']
        right_eye = landmarks['right_eye']

        # Calculate Eye Aspect Ratio (EAR) for both eyes
        left_ear = eye_aspect_ratio(np.array(left_eye))
        right_ear = eye_aspect_ratio(np.array(right_eye))
        ear = (left_ear + right_ear) / 2.0

        # Check if the eye aspect ratio is below the blink threshold
        if ear < config.EYE_AR_THRESH:
            eyes_closed_for_frames += 1
            logger.debug(f"EAR={ear:.2f} (Below Threshold) - Eyes closed frames: {eyes_closed_for_frames}")
        else:
            # If eyes were closed for a sufficient number of frames, count it as a blink
            if eyes_closed_for_frames >= config.EYE_AR_CONSEC_FRAMES:
                blink_counter += 1
                logger.info(f"Blink detected! Total blinks: {blink_counter}")
                live = True # Liveness confirmed for this check interval
            # Reset the eye frame counter
            eyes_closed_for_frames = 0
            logger.debug(f"EAR={ear:.2f} (Above Threshold) - Eyes open.")


        # Reset blink counter periodically if needed, or just rely on recent detection?
        # For now, if a blink happened recently, we consider it live.
        # You might want a timeout for the blink_counter.
        if live:
            blink_counter = 1 # Reset to 1 after detection, requiring a new blink later
            return True
        else:
            # If no blink detected in this interval, reset counter if it was > 0 before
            # This makes it require blinks more consistently.
            # if blink_counter > 0: blink_counter = 0 # Optional: reset if no blink *this interval*
            return False # No blink detected in this check interval


    def process_frame(self, frame_rgb, frame_count):
        """Combined processing: detect, check liveness, recognize."""
        face_locations, face_encodings, face_landmarks = self.detect_and_encode(frame_rgb)

        # --- Liveness Check ---
        # Pass face landmarks to the liveness check
        is_live = self.check_liveness_blink(face_landmarks, frame_count)

        recognized_data = []
        if face_encodings:
            if is_live:
                logger.debug("Liveness check PASSED (Blink detected recently).")
                recognized_data = self.recognize_faces(face_encodings)
            else:
                logger.debug("Liveness check FAILED (No recent blink). Treating as Unknown.")
                # Treat non-live faces as unknown regardless of recognition result
                recognized_data = [{'id': None, 'name': f"{config.UNKNOWN_PERSON_LABEL} (Liveness?)", 'distance': 1.0} for _ in face_encodings]
        else:
             # No faces detected, reset blink state
             global eyes_closed_for_frames
             eyes_closed_for_frames = 0
             logger.debug("No faces detected.")


        return face_locations, recognized_data, is_live