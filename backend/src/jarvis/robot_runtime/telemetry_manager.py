from jarvis.memory.local_db import LocalDatabase
from jarvis.common.logger import setup_logger

logger = setup_logger()

class TelemetryManager:
    def __init__(self):
        self.db = LocalDatabase()
        
    def update_vision_state(self, detected_objects: list):
        """Converts a list of YOLOv8 objects into a comma-separated string and saves it."""
        if not detected_objects:
            reading_str = "None"
        else:
            reading_str = ", ".join(detected_objects)
            
        self.db.log_telemetry(sensor_type="vision_yolov8", reading=reading_str)
        
    def get_current_vision_context(self):
        """Retrieves what the robot currently sees, used by the AI brain."""
        state = self.db.get_latest_telemetry(sensor_type="vision_yolov8")
        return state if state else "Nothing detected."

    def update_ultrasonic_distance(self, distance_cm: float):
        """Logs the distance from the front sensor."""
        self.db.log_telemetry(sensor_type="ultrasonic_front", reading=str(distance_cm))