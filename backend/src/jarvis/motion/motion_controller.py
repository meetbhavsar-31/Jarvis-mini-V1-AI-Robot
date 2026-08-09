import os
import yaml
import requests
import time
from jarvis.common.logger import setup_logger

logger = setup_logger()

class MotionController:
    def __init__(self):
        # Calculate root directory path (4 levels up from motion/)
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
        config_path = os.path.join(root_dir, "config", "robot.yaml")
        
        with open(config_path, 'r') as file:
            self.config = yaml.safe_load(file)
            
        self.robot_ip = self.config['hardware']['robot_ip']
        logger.info(f"Motion Controller Initialized. Target Robot IP: {self.robot_ip}")

    def execute_movement(self, direction: str, duration_seconds: float) -> str:
        """Sends movement commands to the ESP32 web server."""
        logger.info(f"Moving {direction} for {duration_seconds} seconds.")
        valid_directions = ["forward", "backward", "left", "right", "stop"]
        
        if direction not in valid_directions:
            return f"Error: Invalid direction '{direction}'."
        
        try:
            # Send the initial move command to the ESP32
            url = f"{self.robot_ip}/move?dir={direction}"
            requests.get(url, timeout=2)
            
            # If a duration is provided, wait and then automatically stop
            if direction != "stop" and duration_seconds > 0:
                time.sleep(duration_seconds)
                requests.get(f"{self.robot_ip}/move?dir=stop", timeout=2)
                
            return f"Successfully moved {direction} for {duration_seconds} seconds."
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Hardware communication error: {e}")
            return "Failed to move. I cannot reach the ESP32 hardware on the network."

    def execute_eye_color(self, red: int, green: int, blue: int) -> str:
        """Sends RGB eye color update commands to the ESP32 hardware."""
        logger.info(f"Sending Eye Color to Hardware: RGB({red}, {green}, {blue})")
        
        try:
            # Construct the endpoint URL for eye color control on the ESP32
            url = f"{self.robot_ip}/eyes?r={red}&g={green}&b={blue}"
            requests.get(url, timeout=2)
            return f"Successfully updated eye color to RGB({red}, {green}, {blue})."
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Hardware communication error (Eyes): {e}")
            return "Failed to update eye color. I cannot reach the ESP32 hardware on the network."