import cv2
import os
import yaml
import threading
import time
from ultralytics import YOLO
from jarvis.common.logger import setup_logger
from jarvis.robot_runtime.telemetry_manager import TelemetryManager

logger = setup_logger()

class VisionPipeline:
    def __init__(self):
        # Calculate root directory path (4 levels up from ai/ to project root)
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
        config_path = os.path.join(root_dir, "config", "camera.yaml")
        
        with open(config_path, 'r') as file:
            self.config = yaml.safe_load(file)['vision']
            
        self.stream_url = self.config['stream_url']
        self.conf_threshold = self.config['confidence_threshold']
        self.model_name = self.config['model']
        
        logger.info(f"Loading YOLO model ({self.model_name})...")
        try:
            self.model = YOLO(self.model_name)
            logger.info(f"YOLO Vision Model ({self.model_name}) Initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to load YOLO model ({self.model_name}): {e}")
            raise

        self.telemetry = TelemetryManager()
        self.running = False
        self.latest_frame = None
        self.cap = None
        self.thread = None

    def start_stream(self):
        """Starts background frame processing in a separate thread."""
        if self.running:
            logger.warning("Vision pipeline thread is already running.")
            return

        self.running = True
        self.thread = threading.Thread(target=self._process_loop, daemon=True)
        self.thread.start()
        logger.info(f"Vision pipeline thread started for: {self.stream_url}")

    def _open_capture_source(self, source):
        """Helper method to open capture device with stream stability settings."""
        if isinstance(source, int):
            cap = cv2.VideoCapture(source)
        else:
            # Force FFMPEG backend for robust network stream parsing
            cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
            
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _process_loop(self):
        # Handle integer camera IDs (webcam) vs URL strings (ESP32-CAM)
        if isinstance(self.stream_url, int) or (isinstance(self.stream_url, str) and self.stream_url.isdigit()):
            capture_source = int(self.stream_url)
        else:
            capture_source = self.stream_url

        self.cap = self._open_capture_source(capture_source)
        consecutive_failures = 0  

        # COCO dataset label remapping dictionary (fixes cardboard boxes misclassified as vase/suitcase/book)
        LABEL_MAP = {
            "vase": "box",
            "suitcase": "box/package",
            "book": "box/paper item"
        }

        try:
            while self.running:
                ret, frame = self.cap.read()

                # Handle connection drops / frame capture failures
                if not ret:
                    consecutive_failures += 1
                    time.sleep(0.1)
                    
                    if consecutive_failures > 15:
                        logger.warning(f"ESP32-CAM stream lost. Reconnecting to {self.stream_url}...")
                        self.cap.release()
                        time.sleep(1.0)
                        self.cap = self._open_capture_source(capture_source)
                        consecutive_failures = 0
                    continue

                consecutive_failures = 0  # Reset counter on successful frame read

                # Serve initial frame instantly so the dashboard opens without blocking
                if self.latest_frame is None:
                    self.latest_frame = frame

                # Run YOLO detection with optimized image size (imgsz=256) for smooth CPU frame rates
                results = self.model(frame, conf=self.conf_threshold, imgsz=256, verbose=False)
                annotated_frame = results[0].plot()

                # Collect unique detected object names with custom label remapping
                detected_objects = []
                for box in results[0].boxes:
                    class_id = int(box.cls[0])
                    raw_name = self.model.names[class_id]
                    class_name = LABEL_MAP.get(raw_name, raw_name)
                    
                    if class_name not in detected_objects:
                        detected_objects.append(class_name)

                # Update real-time vision telemetry in SQLite & store annotated frame
                self.telemetry.update_vision_state(detected_objects)
                self.latest_frame = annotated_frame

        finally:
            if self.cap:
                self.cap.release()
            logger.info("Vision processing thread terminated and resources released.")

    def get_latest_frame(self):
        """Returns the current annotated OpenCV frame instantly."""
        return self.latest_frame

    def stop_stream(self):
        """Stops vision processing gracefully."""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        logger.info("Vision pipeline stop signal sent.")