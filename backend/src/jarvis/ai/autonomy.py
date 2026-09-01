import os
import time
import urllib.request
import numpy as np
import requests
import cv2
from dotenv import load_dotenv
from ultralytics import YOLO

load_dotenv()

# Extract IPs
esp32_ip = os.getenv("ESP32_IP", "http://192.168.29.173").rstrip("/")
ROBOT_CONTROL_URL = f"{esp32_ip}/move?dir="
cam_stream_url = os.getenv("ESP32_CAM_STREAM_URL", "http://192.168.29.175/stream")
CAMERA_URL = cam_stream_url.replace("/stream", "/cam-hi.jpg") if "/stream" in cam_stream_url else f"{cam_stream_url.rstrip('/')}/cam-hi.jpg"

TRACKING_ACTIVE = False

# Load YOLO model
try:
    model = YOLO("yolov8n.pt")
except Exception as e:
    print(f"YOLO Load Error: {e}")

def get_frame_from_esp32():
    try:
        req = urllib.request.Request(CAMERA_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=1.5) as img_resp:
            imgnp = np.array(bytearray(img_resp.read()), dtype=np.uint8)
            return cv2.imdecode(imgnp, cv2.IMREAD_COLOR)
    except Exception:
        return None

def send_movement(direction: str):
    try:
        requests.get(f"{ROBOT_CONTROL_URL}{direction}", timeout=0.5)
        print(f"[AUTONOMY] Moved: {direction}")
    except:
        pass

def stop_tracking_loop():
    global TRACKING_ACTIVE
    TRACKING_ACTIVE = False
    send_movement("stop")

def start_tracking_loop():
    global TRACKING_ACTIVE
    TRACKING_ACTIVE = True
    print("[AUTONOMY] Tracking engaged. Hunting for humans...")

    while TRACKING_ACTIVE:
        frame = get_frame_from_esp32()
        if frame is None:
            time.sleep(0.2)
            continue

        height, width, _ = frame.shape
        left_bound, right_bound = int(width * 0.35), int(width * 0.65)
        
        results = model.predict(frame, classes=[0], conf=0.5, verbose=False)
        person_detected = False

        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                box_width = x2 - x1
                person_center_x = x1 + (box_width // 2)
                person_detected = True

                if box_width > (width * 0.60): send_movement("stop")
                elif person_center_x < left_bound: send_movement("left")
                elif person_center_x > right_bound: send_movement("right")
                else: send_movement("forward")
                break
            if person_detected: break

        if not person_detected:
            send_movement("stop")

        time.sleep(0.1)