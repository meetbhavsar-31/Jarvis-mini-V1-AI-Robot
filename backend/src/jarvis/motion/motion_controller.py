import os
import requests
import time
from dotenv import load_dotenv
from jarvis.common.logger import setup_logger

# Load environment variables from the .env file in your root folder
load_dotenv()

logger = setup_logger()

class MotionController:
    def __init__(self):
        # Load ESP32 IP centrally from .env (replaces old robot.yaml logic)
        self.robot_ip = os.getenv("ESP32_IP", "http://jarvis.local").rstrip("/")
        logger.info(f"Motion Controller Initialized. Target Robot IP: {self.robot_ip}")

    def execute_movement(self, direction: str, duration_seconds: float) -> str:
        """Sends movement commands to the ESP web server."""
        logger.info(f"Moving {direction} for {duration_seconds} seconds.")
        valid_directions = ["forward", "backward", "left", "right", "stop"]
        
        if direction not in valid_directions:
            return f"Error: Invalid direction '{direction}'."
        
        try:
            # Send the initial move command to the ESP
            url = f"{self.robot_ip}/move?dir={direction}"
            requests.get(url, timeout=2)
            
            # If a duration is provided, wait and then automatically stop
            if direction != "stop" and duration_seconds > 0:
                time.sleep(duration_seconds)
                requests.get(f"{self.robot_ip}/move?dir=stop", timeout=2)
                
            return f"Successfully moved {direction} for {duration_seconds} seconds."
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Hardware communication error: {e}")
            return "Failed to move. I cannot reach the ESP hardware on the network."

    def execute_eye_color(self, red: int, green: int, blue: int) -> str:
        """Sends RGB eye color update commands to the ESP hardware."""
        logger.info(f"Sending Eye Color to Hardware: RGB({red}, {green}, {blue})")
        
        try:
            url = f"{self.robot_ip}/eyes?r={red}&g={green}&b={blue}"
            requests.get(url, timeout=2)
            return f"Successfully updated eye color to RGB({red}, {green}, {blue})."
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Hardware communication error (Eyes): {e}")
            return "Failed to update eye color. I cannot reach the ESP hardware on the network."

    def get_distance(self) -> float:
        """Fetches the ultrasonic sensor distance from the ESP web server."""
        try:
            # Ask the ESP for the current distance
            url = f"{self.robot_ip}/distance"
            response = requests.get(url, timeout=1)
            
            if response.status_code == 200:
                # Convert the returned text (e.g., "15.5") into a float
                return float(response.text.strip())
            
            return 0.0
        except Exception:
            # Suppress logging here to prevent terminal flooding (runs every 0.2s)
            return 0.0