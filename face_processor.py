# face_processor.py
import face_recognition
import numpy as np
import cv2
import config
import logging

logger = logging.getLogger(__name__)




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
        # Using "hog" is faster but less accurate than "cnn"
        face_locations = face_recognition.face_locations(frame_rgb, model="hog")
        if not face_locations:
            return [], [] # Return empty lists if no faces found

        # No need to compute landmarks if not doing blink detection
        face_encodings = face_recognition.face_encodings(frame_rgb, face_locations)

        return face_locations, face_encodings # Only return locations and encodings

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


    def process_frame(self, frame_rgb, frame_count):
        """Combined processing: detect and recognize."""
        # Get locations and encodings
        face_locations, face_encodings = self.detect_and_encode(frame_rgb)

        recognized_data = []
        if face_encodings:
            # Directly recognize faces - no liveness check
            logger.debug("Performing face recognition.")
            recognized_data = self.recognize_faces(face_encodings)
        else:
            logger.debug("No faces detected.")

        # Return only locations and recognized data
        return face_locations, recognized_data