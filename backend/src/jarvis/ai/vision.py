import cv2
import os
import threading
import time
import numpy as np
import requests
from dotenv import load_dotenv
from jarvis.common.logger import setup_logger

try:
    from jarvis.robot_runtime.telemetry_manager import TelemetryManager
except ImportError:
    try:
        from jarvis.motion.telemetry_manager import TelemetryManager
    except ImportError:
        TelemetryManager = None

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

load_dotenv()
logger = setup_logger()


class VisionPipeline:
    # NEW: maps common spoken words to the actual YOLO/COCO class names,
    # since people rarely say the exact label ("follow the guy" should
    # still hit "person"; "find my phone" should hit "cell phone").
    # Extend this as you notice mismatches in practice.
    OBJECT_SYNONYMS = {
        "human": "person", "man": "person", "woman": "person", "guy": "person",
        "people": "person", "someone": "person", "me": "person", "you": "person",
        "phone": "cell phone", "mobile": "cell phone", "cellphone": "cell phone",
        "laptop computer": "laptop", "notebook": "laptop",
        "chair": "chair", "sofa": "couch", "couch": "couch",
        "bottle": "bottle", "cup": "cup", "book": "book",
        "backpack": "backpack", "bag": "backpack",
    }

    # NEW: a detection older than this is considered stale and ignored by
    # get_object_bbox()/get_person_bbox()-style lookups, so the robot
    # doesn't keep "seeing" and chasing something that already left frame.
    # Tunable: if your laptop is slow and YOLO inference regularly takes
    # longer than this, raise it -- otherwise everything will look
    # perpetually "not detected" even though it's just running a bit behind.
    DETECTION_STALE_SECONDS = 3.5

    def __init__(self):
        self.stream_url = os.getenv("ESP32_CAM_STREAM_URL", "http://192.168.29.175/stream")
        self.telemetry = TelemetryManager() if TelemetryManager else None
        self.running = False
        self.latest_frame = None
        self.last_frame_time = 0.0
        self.thread = None
        self.lock = threading.Lock()

        # YOLO11n Offline Object Detection State
        self.yolo_model = None
        self.detected_objects = []
        self.last_detection_time = 0.0  # NEW: timestamp of the most recent YOLO pass
        self.yolo_lock = threading.Lock()
        # NEW: single-flight guard. Without this, a new detection thread was
        # spawned every 4th frame regardless of whether the previous one had
        # finished. On a CPU-bound laptop, YOLO inference can take longer
        # than 4 frames' worth of time, so threads piled up and could finish
        # OUT OF ORDER -- an older (stale) result could overwrite a newer
        # one, making follow/tracking silently use outdated bounding boxes.
        self._yolo_busy = False
        self._load_yolo_model()

    def _load_yolo_model(self, model_path: str = "yolo11n.pt"):
        if YOLO is None:
            logger.warning("ultralytics not installed. YOLO detection disabled.")
            return
        try:
            self.yolo_model = YOLO(model_path)
            logger.info(f"YOLO11n object detection model loaded ({model_path}).")
        except Exception as e:
            logger.error(f"Failed to load YOLO model: {e}. Object detection disabled.")
            self.yolo_model = None

    def _run_yolo_detection(self, frame):
        if self.yolo_model is None:
            return
        with self.yolo_lock:
            self._yolo_busy = True
        try:
            results = self.yolo_model.predict(frame, verbose=False, conf=0.35)
            detections = []
            for r in results:
                for box in r.boxes:
                    label = self.yolo_model.names[int(box.cls[0])]
                    confidence = float(box.conf[0])
                    xyxy = box.xyxy[0].tolist()
                    detections.append({
                        "label": label,
                        "confidence": round(confidence, 2),
                        "box": [round(c, 1) for c in xyxy]
                    })
            with self.yolo_lock:
                self.detected_objects = detections
                self.last_detection_time = time.time()
        except Exception as e:
            logger.error(f"YOLO detection error: {e}")
        finally:
            # NEW: always release the single-flight guard, even on error,
            # otherwise one failed inference permanently disables detection.
            with self.yolo_lock:
                self._yolo_busy = False

    def start_stream(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._process_loop, daemon=True)
        self.thread.start()
        logger.info(f"Persistent Vision stream started for: {self.stream_url}")

    def _process_loop(self):
        headers = {"User-Agent": "Mozilla/5.0"}

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
                            self._frame_counter = getattr(self, "_frame_counter", 0) + 1
                            if self.yolo_model is not None and self._frame_counter % 4 == 0:
                                with self.yolo_lock:
                                    busy = self._yolo_busy
                                # NEW: only spawn a new detection thread if the
                                # previous one has actually finished (see the
                                # single-flight comment in __init__/above).
                                if not busy:
                                    threading.Thread(target=self._run_yolo_detection, args=(frame.copy(),), daemon=True).start()

                            with self.lock:
                                self.latest_frame = frame
                                self.last_frame_time = time.time()

            except Exception as e:
                logger.warning(f"ESP32 stream reconnecting: {e}")
                time.sleep(1.0)

    def get_latest_frame(self):
        with self.lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def get_yolo_detections(self, ignore_staleness: bool = False):
        with self.yolo_lock:
            # NEW: if the last YOLO pass is too old (camera lagging, YOLO
            # thread backed up, object left frame a while ago), treat it as
            # "nothing detected" rather than returning ghost detections.
            if not ignore_staleness and self.last_detection_time:
                age = time.time() - self.last_detection_time
                if age > self.DETECTION_STALE_SECONDS:
                    return []
            return list(self.detected_objects)

    def get_detected_labels(self):
        return list(set(obj["label"] for obj in self.get_yolo_detections()))

    def get_person_bbox(self) -> dict | None:
        """
        Locates the largest 'person' detected by YOLO (closest to the robot).
        Returns bounding metrics used by the Follow-Me PID loop.
        """
        detections = self.get_yolo_detections()
        person_boxes = [d for d in detections if d["label"] == "person"]
        if not person_boxes:
            return None

        largest_person = None
        max_area = 0.0

        for p in person_boxes:
            x1, y1, x2, y2 = p["box"]
            w = max(0.0, x2 - x1)
            h = max(0.0, y2 - y1)
            area = w * h
            if area > max_area:
                max_area = area
                largest_person = {
                    "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                    "w": w, "h": h,
                    "center_x": x1 + (w / 2.0),
                    "center_y": y1 + (h / 2.0),
                    "area": area,
                    "confidence": p["confidence"]
                }
        return largest_person

    def get_object_bbox(self, label: str) -> dict | None:
        """
        NEW: Generic version of get_person_bbox() for ANY YOLO/COCO class
        label, so Jarvis can follow/navigate to things it wasn't hardcoded
        to track (chairs, bottles, backpacks, etc.), not just people.

        Matching order:
          1. Run the spoken label through OBJECT_SYNONYMS (e.g. "guy" -> "person").
          2. Exact (case-insensitive) match against YOLO class names.
          3. Loose substring match as a fallback (e.g. "phone" ~ "cell phone").
        Returns the largest/closest match's bounding metrics, or None if
        nothing matching is currently (and recently) visible.
        """
        if not label:
            return None

        label = label.lower().strip()
        label = self.OBJECT_SYNONYMS.get(label, label)

        detections = self.get_yolo_detections()
        if not detections:
            return None

        exact = [d for d in detections if d["label"].lower() == label]
        matches = exact if exact else [
            d for d in detections
            if label in d["label"].lower() or d["label"].lower() in label
        ]
        if not matches:
            return None

        best = None
        max_area = 0.0
        for m in matches:
            x1, y1, x2, y2 = m["box"]
            w = max(0.0, x2 - x1)
            h = max(0.0, y2 - y1)
            area = w * h
            if area > max_area:
                max_area = area
                best = {
                    "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                    "w": w, "h": h,
                    "center_x": x1 + (w / 2.0),
                    "center_y": y1 + (h / 2.0),
                    "area": area,
                    "confidence": m["confidence"],
                    "label": m["label"],
                }
        return best

    def get_dominant_color_direction(self, color_name: str = "red") -> dict:
        """
        Segment a color using OpenCV HSV filtering and return relative steering direction.
        Supported colors: red, green, blue, yellow.
        """
        frame = self.get_latest_frame()
        if frame is None:
            return {"found": False, "direction": "none", "area": 0}

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        color = color_name.lower().strip()

        if color == "red":
            mask1 = cv2.inRange(hsv, np.array([0, 120, 70]), np.array([10, 255, 255]))
            mask2 = cv2.inRange(hsv, np.array([170, 120, 70]), np.array([180, 255, 255]))
            mask = mask1 | mask2
        elif color == "green":
            mask = cv2.inRange(hsv, np.array([35, 80, 70]), np.array([85, 255, 255]))
        elif color == "blue":
            mask = cv2.inRange(hsv, np.array([95, 100, 70]), np.array([135, 255, 255]))
        elif color == "yellow":
            mask = cv2.inRange(hsv, np.array([20, 100, 100]), np.array([35, 255, 255]))
        else:
            return {"found": False, "direction": "none", "area": 0}

        # Morphological cleanup
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.erode(mask, kernel, iterations=1)
        mask = cv2.dilate(mask, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return {"found": False, "direction": "none", "area": 0}

        largest_c = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest_c)

        # Minimum pixel threshold to avoid noise
        if area < 1200:
            return {"found": False, "direction": "none", "area": area}

        M = cv2.moments(largest_c)
        if M["m00"] == 0:
            return {"found": False, "direction": "none", "area": area}

        cx = int(M["m10"] / M["m00"])
        frame_w = frame.shape[1]

        if cx < frame_w * 0.38:
            direction = "left"
        elif cx > frame_w * 0.62:
            direction = "right"
        else:
            direction = "center"

        return {"found": True, "direction": direction, "area": int(area), "cx": cx}

    def get_recognized_faces(self):
        return []

    def learn_new_face(self, name: str) -> tuple[bool, str]:
        return False, "Face biometric storage disabled; identity saved in ChromaDB memory."

    def generate_mjpeg_stream(self):
        while self.running:
            frame = self.get_latest_frame()
            if frame is not None:
                success, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if success:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(0.04)

    def diagnose(self) -> dict:
        with self.lock:
            has_frame = self.latest_frame is not None
            age = time.time() - self.last_frame_time if self.last_frame_time else None
        return {
            "stream_url": self.stream_url,
            "stream_running": self.running,
            "has_frame": has_frame,
            "last_frame_age_seconds": round(age, 1) if age is not None else None,
            "frame_considered_stale": (age is not None and age > 5.0),
            "yolo_loaded": self.yolo_model is not None,
            "current_yolo_detections": self.get_yolo_detections(),
        }

    def stop_stream(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
