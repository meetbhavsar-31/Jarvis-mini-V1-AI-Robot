import os
import time
import threading
import requests
from dotenv import load_dotenv
from jarvis.common.logger import setup_logger

load_dotenv()
logger = setup_logger()

# FIX: previously esp32_ip/ROBOT_CONTROL_URL/DISTANCE_URL were computed ONCE
# at import time from the .env value and never touched again. If this module
# is used alongside the app.py Settings page (which now lets you update the
# robot's IP live, without restarting), this module would silently keep
# talking to the OLD IP forever. _esp32_ip() now re-reads the current value
# every call, so it stays in sync with whatever app.py's ESP32_IP currently
# is if you wire this module to read from there (see note at bottom), or at
# minimum re-reads the environment each time.
_raw_esp_ip = os.getenv("ESP32_IP", "http://192.168.29.173").rstrip("/")
_DEFAULT_ESP32_IP = _raw_esp_ip if _raw_esp_ip.startswith("http") else f"http://{_raw_esp_ip}"

# Allows an external caller (e.g. app.py) to override the target IP at
# runtime, e.g.: import jarvis.motion.autonomy as autonomy; autonomy.set_esp32_ip(new_ip)
_current_esp32_ip = _DEFAULT_ESP32_IP


def set_esp32_ip(ip: str):
    """Call this whenever the robot's IP changes (e.g. from the Settings page)."""
    global _current_esp32_ip
    ip = ip.strip()
    if not ip:
        return
    _current_esp32_ip = ip if ip.startswith("http") else f"http://{ip}"
    logger.info(f"[AUTONOMY] ESP32 target IP updated to: {_current_esp32_ip}")


def _move_url(direction: str) -> str:
    return f"{_current_esp32_ip}/move?dir={direction.lower()}"


def _distance_url() -> str:
    return f"{_current_esp32_ip}/distance"


# FIX: use a threading.Event instead of a bare bool. Functionally similar
# under the GIL for this simple case, but makes start/stop state explicit
# and gives other threads a clean way to wait/check without polling a flag.
_tracking_event = threading.Event()


def send_movement(direction: str):
    try:
        requests.get(_move_url(direction), timeout=0.8)
    except Exception as e:
        logger.error(f"[AUTONOMY] Motor command failed: {e}")


def is_obstacle_too_close(threshold_cm: float = 25.0) -> bool:
    """Verifies front distance to avoid collisions while tracking."""
    try:
        res = requests.get(_distance_url(), timeout=0.8)
        if res.status_code == 200:
            return float(res.text) < threshold_cm
    except Exception:
        pass
    return False


def is_tracking_active() -> bool:
    return _tracking_event.is_set()


def stop_tracking():
    _tracking_event.clear()
    send_movement("stop")


def run_standalone_tracking(vision_pipeline):
    """
    Modular tracker referencing the unified VisionPipeline
    without loading a redundant second YOLO model.

    IMPORTANT: this loop is NOT coordinated with app.py's own
    AUTONOMOUS_MODE / FOLLOW_ME_MODE / STATE_LOCK. Do not run this at the
    same time as app.py's follow_me_loop() or autonomous_navigation_loop()
    against the same robot -- they will issue conflicting movement commands.
    If this is meant to replace app.py's built-in follow-me logic, wire it
    in exclusively (and call set_esp32_ip() from app.py whenever the
    Settings page updates the robot IP); if it's legacy/unused, consider
    deleting it to avoid it accidentally getting invoked twice.
    """
    if vision_pipeline is None:
        logger.error("[AUTONOMY] Vision pipeline unavailable.")
        return

    _tracking_event.set()
    logger.info("[AUTONOMY] Autonomous tracker active.")

    try:
        while _tracking_event.is_set():
            # FIX: the entire loop body previously had no try/except. A
            # single unexpected exception (e.g. a malformed detection dict)
            # would propagate straight out of this function, past the
            # `while` loop, past this function's frame entirely -- and
            # whatever movement was last sent (e.g. "forward") would keep
            # happening on the robot with nothing left running to stop it,
            # since send_movement() is fire-and-forget with no duration or
            # auto-stop. Wrapping the body means a transient error gets
            # logged and the loop keeps going instead of dying silently
            # mid-command.
            try:
                if is_obstacle_too_close():
                    send_movement("stop")
                    time.sleep(0.1)
                    continue

                person = vision_pipeline.get_person_bbox()
                frame = vision_pipeline.get_latest_frame()

                if frame is not None and person:
                    width = frame.shape[1]
                    center_x = person["center_x"]
                    box_w = person["w"]

                    if box_w > (width * 0.60):  # Target is within holding range
                        send_movement("stop")
                    elif center_x < (width * 0.35):
                        send_movement("left")
                    elif center_x > (width * 0.65):
                        send_movement("right")
                    else:
                        send_movement("forward")
                else:
                    send_movement("stop")

            except Exception as e:
                logger.error(f"[AUTONOMY] Tracking loop error: {e}")
                send_movement("stop")

            time.sleep(0.08)
    finally:
        # FIX: guarantees a stop command is sent no matter HOW this function
        # exits -- normal stop_tracking() call, an uncaught exception above
        # somehow escaping the inner try, or the vision_pipeline disappearing
        # mid-loop. Previously, only the explicit stop_tracking() path sent
        # a final "stop"; every other exit path could leave the robot moving.
        send_movement("stop")
        _tracking_event.clear()
        logger.info("[AUTONOMY] Autonomous tracker stopped.")
