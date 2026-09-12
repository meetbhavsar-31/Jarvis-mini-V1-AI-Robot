import os
import time
import threading
import requests
from dotenv import load_dotenv
from jarvis.common.logger import setup_logger

load_dotenv()
logger = setup_logger()

class MotionController:
    def __init__(self):
        # Load ESP32 IP centrally from .env (replaces old robot.yaml logic)
        self.robot_ip = os.getenv("ESP32_IP", "http://jarvis.local").rstrip("/")
        self._ip_lock = threading.Lock()
        self._last_distance_fail_log = 0.0
        logger.info(f"Motion Controller Initialized. Target Robot IP: {self.robot_ip}")

    def set_robot_ip(self, ip: str):
        """
        NEW: lets callers update the target IP at runtime.

        FIX: previously self.robot_ip was set once here from the .env value
        and NEVER touched again for the lifetime of the process. app.py's
        Settings page updates app.py's own module-level ESP32_IP global (so
        movement commands built directly in app.py, via
        execute_tracked_movement(), correctly picked up an IP change) --
        but MotionController kept using the OLD ip forever for
        get_distance() / execute_movement() / execute_eye_color(). That
        mismatch meant: after changing the robot's IP on the Settings page,
        driving still worked (app.py's own calls) but distance sensing kept
        silently failing against the wrong, stale address -- which, given
        bug #2 below, looked like the robot randomly refusing to approach
        anything. app.py must call this whenever ESP32_IP changes (on
        startup, right after MotionController() is constructed, and again
        inside the /api/settings POST handler).
        """
        ip = ip.strip().rstrip("/")
        if not ip:
            return
        new_ip = ip if ip.startswith("http") else f"http://{ip}"
        with self._ip_lock:
            self.robot_ip = new_ip
        logger.info(f"MotionController target IP updated to: {self.robot_ip}")

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

    def get_distance(self):
        """
        Fetches the ultrasonic sensor distance from the ESP web server.

        FIX: previously returned 0.0 on ANY failure -- timeout, connection
        error, non-200 response, or a parse error -- which is
        indistinguishable from a genuine "0cm, something is touching the
        sensor" reading. Every caller in app.py used patterns like
        `elif 0 < dist < 35: backward` which treats 0.0 as neither "close"
        nor "far", silently falling through to a full stop. Given how often
        your logs show ESP32 request timeouts, this meant every transient
        network hiccup during follow-me / color-hunt / autonomy silently
        halted the robot instead of continuing to approach its target --
        looking exactly like "motor not spinning," with zero error signal
        to go on. Now returns None on failure so callers can tell "no
        reading available" apart from "reading is genuinely zero," and logs
        failures (rate-limited to once per 5s, since this is polled at
        roughly 5-10Hz by the various tracking loops -- logging every single
        failed call would flood the terminal).
        """
        try:
            url = f"{self.robot_ip}/distance"
            response = requests.get(url, timeout=1)

            if response.status_code == 200:
                return float(response.text.strip())

            self._log_distance_failure(f"HTTP {response.status_code}")
            return None
        except Exception as e:
            self._log_distance_failure(str(e))
            return None

    def _log_distance_failure(self, reason: str):
        now = time.time()
        if now - self._last_distance_fail_log > 5.0:
            logger.warning(f"[MOTION] Distance sensor read failed (further failures suppressed for 5s): {reason}")
            self._last_distance_fail_log = now
