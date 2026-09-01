import cv2
import os
import threading
import time
import numpy as np
import requests
from dotenv import load_dotenv
from jarvis.common.logger import setup_logger
from jarvis.robot_runtime.telemetry_manager import TelemetryManager

try:
    import face_recognition
except ImportError:
    face_recognition = None

load_dotenv()
logger = setup_logger()

class VisionPipeline:
    def __init__(self):
        self.stream_url = os.getenv("ESP32_CAM_STREAM_URL", "http://192.168.29.175/stream")
        self.telemetry = TelemetryManager()
        self.running = False
        self.latest_frame = None
        self.thread = None
        self.lock = threading.Lock()

        # Face Recognition Setup
        self.known_face_encodings = []
        self.known_face_names = []
        self.recognized_names = []
        self._load_known_faces()

    def _load_known_faces(self, known_faces_dir="known_faces"):
        """Loads reference photos from the root known_faces directory."""
        if face_recognition is None:
            logger.warning("face_recognition library not installed. Biometric identification disabled.")
            return

        if not os.path.exists(known_faces_dir):
            os.makedirs(known_faces_dir, exist_ok=True)
            logger.info(f"Created '{known_faces_dir}' directory. Place reference images (e.g. Meet.jpg) inside.")
            return

        for filename in os.listdir(known_faces_dir):
            if filename.lower().endswith((".jpg", ".png", ".jpeg")):
                image_path = os.path.join(known_faces_dir, filename)
                try:
                    image = face_recognition.load_image_file(image_path)
                    encodings = face_recognition.face_encodings(image)
                    if encodings:
                        self.known_face_encodings.append(encodings[0])
                        name = os.path.splitext(filename)[0]
                        self.known_face_names.append(name)
                        logger.info(f"Loaded biometric profile for: {name}")
                except Exception as e:
                    logger.error(f"Failed to load face profile {filename}: {e}")

    def start_stream(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._process_loop, daemon=True)
        self.thread.start()
        logger.info(f"Direct Persistent Vision stream thread started for: {self.stream_url}")

    def _process_loop(self):
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        while self.running:
            try:
                response = requests.get(self.stream_url, stream=True, timeout=5, headers=headers)
                if response.status_code != 200:
                    time.sleep(1.0)
                    continue

                bytes_data = bytes()
                for chunk in response.iter_content(chunk_size=4096):
                    if not self.running:
                        break
                    
                    bytes_data += chunk
                    a = bytes_data.find(b'\xff\xd8')
                    b = bytes_data.find(b'\xff\xd9')
                    
                    if a != -1 and b != -1:
                        jpg = bytes_data[a:b+2]
                        bytes_data = bytes_data[b+2:]
                        
                        frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                        if frame is not None:
                            # Run face identification check periodically
                            if face_recognition and self.known_face_encodings:
                                self._identify_faces_in_frame(frame)

                            with self.lock:
                                self.latest_frame = frame

            except Exception as e:
                logger.warning(f"ESP32 stream reconnecting: {e}")
                time.sleep(1.0)

    def _identify_faces_in_frame(self, frame):
        try:
            small_frame = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)
            rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
            
            face_locations = face_recognition.face_locations(rgb_small_frame)
            face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)
            
            current_recognized = []
            for face_encoding in face_encodings:
                matches = face_recognition.compare_faces(self.known_face_encodings, face_encoding, tolerance=0.5)
                name = "Unknown"
                
                if True in matches:
                    first_match_index = matches.index(True)
                    name = self.known_face_names[first_match_index]
                
                current_recognized.append(name)
            
            with self.lock:
                self.recognized_names = current_recognized
        except Exception as e:
            logger.error(f"Face identification error: {e}")

    def get_latest_frame(self):
        with self.lock:
            return self.latest_frame

    def get_recognized_faces(self):
        with self.lock:
            return list(set(self.recognized_names))

    def generate_mjpeg_stream(self):
        while self.running:
            frame = self.get_latest_frame()
            if frame is not None:
                success, buffer = cv2.imencode('.jpg', frame)
                if success:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(0.05)

    def get_detected_labels(self):
        return self.get_recognized_faces()

    def stop_stream(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)