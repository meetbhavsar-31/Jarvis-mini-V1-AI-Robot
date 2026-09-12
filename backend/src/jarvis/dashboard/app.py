import cv2
import re
import os
import json
import time
import uuid
import base64
import random
import threading
import requests
import numpy as np
import wave
import socket
import psutil
import asyncio
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

load_dotenv()

try:
    from gtts import gTTS
    from pydub import AudioSegment
except ImportError:
    AudioSegment = None

from fastapi import FastAPI, Request, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from groq import Groq
from google.genai import types

from jarvis.common.logger import setup_logger
from jarvis.ai.vision import VisionPipeline
from jarvis.ai.brain import JarvisBrain
from jarvis.motion.motion_controller import MotionController
from jarvis.memory.rag import LongTermMemoryManager
from jarvis.storage.cloud_manager import CloudManager
from jarvis.ai.gesture_nav import GestureNavigator
from jarvis.alerts import notifier

try:
    from jarvis.audio.tts import GoogleSpeaker
    tts_en_local = GoogleSpeaker(lang="en", tld="co.uk")
    tts_hi_local = GoogleSpeaker(lang="hi", tld="co.in")
except Exception:
    tts_en_local, tts_hi_local = None, None

logger = setup_logger()
app = FastAPI(title="JARVIS MINI V1 - Master Tactical Dashboard")

gesture_navigator = GestureNavigator()

try:
    from jarvis.ai.local_wake_word import LocalWakeWordListener
    logger.info("Laptop Mic: Local Wake Word Engine Loaded.")
except Exception as e:
    LocalWakeWordListener = None

WAITING_FOR_WAKE_WORD = True
WAKE_WORD_TRIGGER_TIME = 0.0
IGNORE_MIC_UNTIL = 0.0

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
STATIC_DIR = os.path.join(ROOT_DIR, "static")
TEMPLATES_DIR = os.path.join(ROOT_DIR, "templates")
TEMP_AUDIO_DIR = os.path.join(ROOT_DIR, "temp_audio")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(TEMP_AUDIO_DIR, exist_ok=True)

def cleanup_stale_temp_audio(max_age_seconds: float = 3600.0):
    if not os.path.isdir(TEMP_AUDIO_DIR): return
    now = time.time()
    for fname in os.listdir(TEMP_AUDIO_DIR):
        if not (fname.startswith("temp_stt_") or fname.startswith("robot_mic_") or fname.startswith("temp_tts_")): continue
        fpath = os.path.join(TEMP_AUDIO_DIR, fname)
        try:
            if now - os.path.getmtime(fpath) > max_age_seconds: os.remove(fpath)
        except Exception: pass

def require_api_auth(request: Request):
    if not API_AUTH_TOKEN: return
    supplied = request.headers.get("X-API-Token", "")
    if supplied != API_AUTH_TOKEN:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Token header.")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

raw_esp_ip = os.getenv("ESP32_IP", "http://192.168.29.173").strip().rstrip("/")
ESP32_IP = raw_esp_ip if raw_esp_ip.startswith("http") else f"http://{raw_esp_ip}"

# ==========================================
# NEW: PERSISTED ROBOT SETTINGS
# ==========================================
# FIX: settings.html expects GET /api/settings to return the current
# settings and expects POST /api/settings to actually persist and apply
# them. Neither existed before -- the Settings page always showed blank
# defaults, "Save" didn't store anything, and critically, the robot's IP
# address could never be changed without editing .env and restarting the
# whole server. Given your logs showed the motor-board ESP32 repeatedly
# timing out at a fixed IP, this was actively blocking you from just
# typing in the robot's *current* IP and having it work immediately.
SETTINGS_FILE = os.path.join(ROOT_DIR, "jarvis_settings.json")

def _default_settings() -> dict:
    return {
        "robotName": "JARVIS MINI",
        "robotIp": ESP32_IP.replace("http://", "").replace("https://", ""),
        "cameraIp": os.getenv("ESP32_CAM_STREAM_URL", "").replace("http://", "").replace("https://", "").replace("/stream", ""),
        "aiEngine": "groq",
        "baseSpeed": 180,
        "wakeWordEnabled": True,
    }

def load_settings() -> dict:
    defaults = _default_settings()
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            defaults.update({k: v for k, v in saved.items() if k in defaults})
        except Exception as e:
            logger.error(f"Failed to load settings file, using defaults: {e}")
    return defaults

def save_settings_to_disk(settings: dict):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save settings file: {e}")

ROBOT_SETTINGS = load_settings()

# Apply any saved IP overrides immediately at startup (before the rest of
# the app reads ESP32_IP), so a previously-saved correction survives restarts.
if ROBOT_SETTINGS.get("robotIp"):
    _saved_ip = ROBOT_SETTINGS["robotIp"].strip()
    if _saved_ip:
        ESP32_IP = _saved_ip if _saved_ip.startswith("http") else f"http://{_saved_ip}"

WAKE_WORD_ENABLED = ROBOT_SETTINGS.get("wakeWordEnabled", True)

# ==========================================
# NEW: TASK PERSISTENCE / REMINDERS
# ==========================================
REMINDERS_FILE = os.path.join(ROOT_DIR, "jarvis_reminders.json")
REMINDERS_LOCK = threading.RLock()
REMINDERS: list = []

def load_reminders():
    global REMINDERS
    if os.path.exists(REMINDERS_FILE):
        try:
            with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
                REMINDERS = json.load(f)
            return
        except Exception as e:
            logger.error(f"Failed to load reminders file, starting empty: {e}")
    REMINDERS = []

def save_reminders_to_disk():
    try:
        with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(REMINDERS, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save reminders file: {e}")

load_reminders()

def add_reminder(text: str, due_dt: datetime, recurring: str = None) -> dict:
    """recurring: None | 'daily' | 'weekly'"""
    with REMINDERS_LOCK:
        reminder = {
            "id": uuid.uuid4().hex[:8],
            "text": text.strip() or "reminder",
            "due_ts": due_dt.timestamp(),
            "recurring": recurring,
            "done": False,
            "created_ts": time.time(),
        }
        REMINDERS.append(reminder)
        save_reminders_to_disk()
    add_log_event(f"Reminder set: {reminder['text']} @ {due_dt.strftime('%Y-%m-%d %H:%M')}")
    return reminder

def _parse_reminder_datetime(text: str):
    """
    Lightweight natural-language time parser -- no external NLP library
    dependency. Supports:
      "in 10 minutes", "after 10 minutes", "within 10 minutes"
      "in 2 hours", "in 1 hour 30 minutes"
      "at 6pm", "at 6:30 pm", "at 18:30"
      "tomorrow at 9am"
    Returns a datetime, or None if nothing recognizable was found (caller
    should ask the person to rephrase rather than silently guessing).
    """
    t = text.lower().strip()
    now = datetime.now()

    # FIX: previously only "in X minutes/hours" was recognized. "after X
    # minutes" (a very natural way to phrase it) fell through and produced
    # "I couldn't figure out the timing for that" even though it's an
    # unambiguous duration. Now accepts in/after/within as synonyms.
    m = re.search(r"(?:in|after|within)\s+(?:(\d+)\s*(?:hours?|hrs?|h)\b)?\s*(?:(\d+)\s*(?:minutes?|mins?|m)\b)?", t)
    if m and (m.group(1) or m.group(2)):
        hours = int(m.group(1)) if m.group(1) else 0
        minutes = int(m.group(2)) if m.group(2) else 0
        if hours or minutes:
            return now + timedelta(hours=hours, minutes=minutes)

    m = re.search(r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        meridiem = m.group(3)
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if "tomorrow" in t or target <= now:
                target += timedelta(days=1)
            return target

    return None

def _extract_reminder_text(raw_message: str) -> str:
    text = raw_message
    text = re.sub(r"(?i)\bremind me( to)?\b", "", text)
    text = re.sub(r"(?i)\bset a reminder( to)?\b", "", text)
    # FIX: matches the same in/after/within synonyms now accepted by
    # _parse_reminder_datetime -- otherwise the leftover duration phrase
    # (e.g. "after 1 minute") stayed stuck in the reminder's spoken text.
    text = re.sub(r"(?i)\b(in|after|within)\s+\d+\s*(hours?|hrs?|h)\b(\s+\d+\s*(minutes?|mins?|m)\b)?", "", text)
    text = re.sub(r"(?i)\b(in|after|within)\s+\d+\s*(minutes?|mins?|m)\b", "", text)
    text = re.sub(r"(?i)\bat\s+\d{1,2}(:\d{2})?\s*(am|pm)?\b", "", text)
    text = re.sub(r"(?i)\btomorrow\b", "", text)
    return text.strip(" ,.\t")

def reminder_loop():
    logger.info("Reminder scheduler online.")
    while True:
        try:
            now_ts = time.time()
            due_now = []
            with REMINDERS_LOCK:
                for r in REMINDERS:
                    if not r.get("done") and r["due_ts"] <= now_ts:
                        due_now.append(r)

            for r in due_now:
                jarvis_speak(f"Reminder: {r['text']}.")
                notifier.notify_info(f"Reminder: {r['text']}", title="JARVIS Reminder")
                add_log_event(f"Reminder fired: {r['text']}")
                with REMINDERS_LOCK:
                    if r.get("recurring") == "daily":
                        r["due_ts"] = r["due_ts"] + 86400
                    elif r.get("recurring") == "weekly":
                        r["due_ts"] = r["due_ts"] + (86400 * 7)
                    else:
                        r["done"] = True
                    save_reminders_to_disk()
        except Exception as e:
            logger.error(f"Reminder loop error: {e}")
        time.sleep(15)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
groq_client = Groq(api_key=GROQ_API_KEY)
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.6-27b")
OLLAMA_LOCAL_MODEL = os.getenv("OLLAMA_LOCAL_MODEL", "qwen2.5:3b")

STATE_LOCK = threading.RLock()
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "").strip()

CURRENT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "en")
AUTONOMOUS_MODE = False
FOLLOW_ME_MODE = False
COLOR_HUNT_MODE = False
GESTURE_MODE = False
COLOR_HUNT_TARGET = "red"

# NEW: which object label follow-mode is currently locked onto.
# "person" (default) uses vision_pipeline.get_person_bbox(); anything else
# uses vision_pipeline.get_object_bbox(label) (YOLO class-name match).
FOLLOW_TARGET_LABEL = "person"

LAST_SPOKEN_TIME = 0.0
IS_SPEAKING = False
HARD_MUTE = False
SPEAKER_VOLUME_GAIN = 1.0
ACTIVE_TASK = None

BOSS_NAME = "Meet"
TEAM_ROSTER = [("Meet Bhavsar", "Lead and Firmware"), ("Bhakti Nivgane", "Hardware and Power"), ("Shreya Shukla", "A I and Backend Data"), ("Dhara Thakkar", "Vision and Tracking"), ("Janvi Bhatt", "Audio and Dashboard")]
TEAM_PHOTO_TOTAL_CYCLE_TIME = 5.2
PATH_HISTORY = []
SYSTEM_BOOT_TIME = time.time()
ACTIVITY_LOGS = []
executor = ThreadPoolExecutor(max_workers=4)

def get_local_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception: return "127.0.0.1"

LOCAL_LAN_IP = get_local_lan_ip()
LAN_SERVER_ADDRESS = f"{LOCAL_LAN_IP}:8000"

def speak_team_introductions():
    time.sleep(1.0)
    for name, role in TEAM_ROSTER:
        start = time.time()
        file_prefix = name.split()[0].lower()
        try: requests.get(f"{ESP32_IP}/show_member?server={LAN_SERVER_ADDRESS}&file={file_prefix}&name={name}&role={role}", timeout=1.0)
        except Exception: pass
        jarvis_speak(f"{name}. {role}.")
        elapsed = time.time() - start
        if TEAM_PHOTO_TOTAL_CYCLE_TIME - elapsed > 0: time.sleep(TEAM_PHOTO_TOTAL_CYCLE_TIME - elapsed)

def add_log_event(event_text: str):
    now = datetime.now()
    ACTIVITY_LOGS.insert(0, {"timestamp": now.isoformat(timespec="seconds"), "event": event_text})
    if len(ACTIVITY_LOGS) > 50: ACTIVITY_LOGS.pop()

def set_esp32_emotion(emotion: str):
    if not ESP32_IP: return
    try: requests.get(f"{ESP32_IP}/emotion?type={emotion}", timeout=0.4)
    except: pass

def set_esp32_eyes(r: int, g: int, b: int):
    if not ESP32_IP: return
    try: requests.get(f"{ESP32_IP}/eyes?r={r}&g={g}&b={b}", timeout=0.4)
    except: pass

def trigger_esp32_beep():
    if not ESP32_IP: return
    try: requests.get(f"{ESP32_IP}/beep", timeout=0.4)
    except: pass

def send_esp32_stop(retries: int = 3) -> bool:
    for attempt in range(retries):
        try:
            res = requests.get(f"{ESP32_IP}/move?dir=stop", timeout=0.8)
            if res.status_code == 200: return True
        except Exception as e: logger.error(f"send_esp32_stop failed: {e}")
    return False

# NEW: fires an alert without blocking the calling loop. notify_emergency()
# can take up to ~16s worst-case (two channels x 8s timeout each) if the
# network is slow -- fine for a voice-triggered SOS (already inside a
# blocking request/speech flow), but not fine inside a tight background
# loop like autonomous_navigation_loop/battery_monitor_loop, where it would
# delay the next obstacle/person check by that same amount.
def _notify_async(message: str, **kwargs):
    threading.Thread(target=notifier.notify_emergency, args=(message,), kwargs=kwargs, daemon=True).start()

# NEW: defensive wrapper around motion.get_distance(). Several loops
# (follow-me, color-hunt, autonomy) call this every ~100ms.
#
# UPDATE after seeing motion_controller.py: the underlying call never
# actually hangs -- it has its own 1s request timeout and catches all
# exceptions internally. The REAL bug was that it silently returned 0.0 on
# every failure, which every caller's `elif 0 < dist < 35` logic treats as
# neither "close" nor "far" -- so a failed sensor read fell through to a
# full stop every time, which given how often your ESP32 link times out in
# your logs, meant transient network hiccups were silently halting
# follow-me/color-hunt instead of letting the robot keep approaching.
# motion_controller.py now returns None on failure instead of overloading
# 0.0; this wrapper turns that None into a safe default (same "personal
# space" dead-zone value so callers stop rather than guess blindly) plus a
# log line, and still bounds the call with a real timeout as a second line
# of defense in case anything else in the call chain ever blocks.
def get_distance_safe(timeout: float = 0.6, default: float = 50.0) -> float:
    try:
        future = executor.submit(motion.get_distance)
        result = future.result(timeout=timeout)
        if result is None:
            logger.warning("get_distance_safe: sensor read failed (motion.get_distance() returned None).")
            return default
        return result
    except Exception as e:
        logger.warning(f"get_distance_safe fallback triggered ({e}) -- motion.get_distance() call itself failed to complete.")
        return default

# NEW: quick reachability check used before starting any long-running
# autonomous behavior, so failures are reported instead of silently
# doing nothing (this is what was happening with autonomous mode).
def check_esp32_online(timeout: float = 1.0) -> bool:
    if not ESP32_IP: return False
    try:
        res = requests.get(f"{ESP32_IP}/distance", timeout=timeout)
        return res.status_code == 200
    except Exception:
        return False

def execute_tracked_movement(direction: str, duration: float = 1.0):
    try: requests.get(f"{ESP32_IP}/move?dir={direction.lower()}", timeout=1.0)
    except Exception as e: logger.error(f"Failed to reach ESP32: {e}")
    time.sleep(0.05)
    if direction in ["forward", "backward", "left", "right"]:
        with STATE_LOCK: PATH_HISTORY.append((direction, duration))
    if duration > 0 and direction != "stop":
        time.sleep(duration)
        send_esp32_stop(retries=1)

def force_stop_all():
    global AUTONOMOUS_MODE, FOLLOW_ME_MODE, COLOR_HUNT_MODE, GESTURE_MODE, IS_SPEAKING, IS_RECORDING, HARD_MUTE, ACTIVE_TASK, WAITING_FOR_WAKE_WORD
    with STATE_LOCK:
        AUTONOMOUS_MODE = False
        FOLLOW_ME_MODE = False
        COLOR_HUNT_MODE = False
        GESTURE_MODE = False
        IS_SPEAKING = False
        IS_RECORDING = False
        HARD_MUTE = True
        WAITING_FOR_WAKE_WORD = True
        ACTIVE_TASK = None
        AUDIO_BUFFER.clear()
        PATH_HISTORY.clear()
    hardware_stopped = send_esp32_stop(retries=3)
    try: motion.execute_movement("stop", 0.0)
    except: pass
    set_esp32_emotion("happy")
    set_esp32_eyes(0, 255, 204)
    add_log_event("SYSTEM HALTED BY USER" if hardware_stopped else "SYSTEM HALT REQUESTED")
    time.sleep(0.3)
    with STATE_LOCK: HARD_MUTE = False

def reverse_path():
    with STATE_LOCK:
        if not PATH_HISTORY:
            jarvis_speak("I have no path data to reverse, sir.")
            return
        jarvis_speak("Returning to base coordinates.")
    reverse_map = {"forward": "backward", "backward": "forward", "left": "right", "right": "left"}
    while True:
        with STATE_LOCK:
            if not PATH_HISTORY: break
            direction, duration = PATH_HISTORY.pop()
        rev_dir = reverse_map.get(direction, "stop")
        execute_tracked_movement(rev_dir, duration)
        time.sleep(0.2)
    send_esp32_stop(retries=2)
    try: motion.execute_movement("stop", 0.0)
    except: pass
    jarvis_speak("I have successfully returned to my starting point.")

# NEW: actually drives the robot toward a detected object and stops
# when it's close, instead of just speaking about it (fixes the
# "go to the red object" command doing nothing).
#
# FIX (2nd pass): the first version of this function read a "center_x"
# key off vision_pipeline.get_dominant_color_direction(), but that method
# actually returns {"found", "direction", "area", "cx"} — there is no
# "center_x" key. That mismatch meant the color-based path (use_color=True)
# would either crash (None - int) or silently never move. This version
# uses each vision method's *real* return shape: "direction" (left/right/
# center) for color search, and a bbox->offset calculation for object-label
# search via the new vision_pipeline.get_object_bbox().
def navigate_to_target_object(label: str, use_color: bool = False, timeout_seconds: float = 20.0) -> bool:
    global AUTONOMOUS_MODE, FOLLOW_ME_MODE, GESTURE_MODE
    with STATE_LOCK:
        AUTONOMOUS_MODE = False
        FOLLOW_ME_MODE = False
        GESTURE_MODE = False

    set_esp32_emotion("thinking")
    start = time.time()
    reached = False
    misses = 0

    while time.time() - start < timeout_seconds:
        dist = get_distance_safe()

        if use_color:
            data = vision_pipeline.get_dominant_color_direction(label)
            found = bool(data.get("found"))
            direction = data.get("direction", "none")
        else:
            target = vision_pipeline.get_object_bbox(label) if hasattr(vision_pipeline, "get_object_bbox") else None
            found = target is not None
            if found:
                frame = vision_pipeline.get_latest_frame()
                frame_w = frame.shape[1] if frame is not None else 640
                offset_x = target["center_x"] - (frame_w / 2.0)
                if offset_x < -60: direction = "left"
                elif offset_x > 60: direction = "right"
                else: direction = "center"
            else:
                direction = "none"

        if not found:
            misses += 1
            if misses > 12:
                break
            execute_tracked_movement("right", 0.2)
            time.sleep(0.15)
            continue
        misses = 0

        if direction == "left":
            execute_tracked_movement("left", 0.15)
        elif direction == "right":
            execute_tracked_movement("right", 0.15)
        else:  # "center"
            if dist > 30 or dist <= 0:
                execute_tracked_movement("forward", 0.25)
            else:
                send_esp32_stop(retries=2)
                reached = True
                break
        time.sleep(0.12)

    send_esp32_stop(retries=2)
    set_esp32_emotion("happy" if reached else "confused")
    if reached:
        jarvis_speak(f"I have arrived at the {label}, sir.")
    else:
        jarvis_speak(f"I could not close in on the {label} in time, sir.")
    return reached

def on_wake_word_detected():
    global WAITING_FOR_WAKE_WORD, IS_RECORDING, SILENCE_START, WAKE_WORD_TRIGGER_TIME, FOLLOW_ME_MODE, COLOR_HUNT_MODE, GESTURE_MODE
    with STATE_LOCK:
        # NEW: honors the "Enable Local Voice Wake Word" toggle on the
        # Settings page. The underlying listener thread still runs (we don't
        # have access to a start/stop API on LocalWakeWordListener), but
        # trigger callbacks are now ignored while disabled, so the toggle
        # actually does something instead of being a purely cosmetic switch.
        if not WAKE_WORD_ENABLED:
            return
        if IS_SPEAKING or HARD_MUTE or time.time() < IGNORE_MIC_UNTIL:
            return
        if not WAITING_FOR_WAKE_WORD:
            return
        logger.info("Wake word detected! Activating robot ears...")
        WAITING_FOR_WAKE_WORD = False
        WAKE_WORD_TRIGGER_TIME = time.time()
        IS_RECORDING = True
        AUDIO_BUFFER.clear()
        SILENCE_START = None
        FOLLOW_ME_MODE = False
        COLOR_HUNT_MODE = False
        GESTURE_MODE = False

    trigger_esp32_beep()
    set_esp32_emotion("listening")
    set_esp32_eyes(255, 0, 0)
    try: motion.execute_movement("stop", 0.0)
    except: pass

vision_pipeline = VisionPipeline()
vision_pipeline.start_stream()
brain = JarvisBrain(vision_pipeline=vision_pipeline)
motion = MotionController()
# FIX: MotionController.__init__ reads ESP32_IP straight from the raw .env
# value, not app.py's own ESP32_IP (which by this point may already reflect
# a saved Settings-page override -- see load_settings() above). Sync it
# explicitly so distance sensing starts out consistent with movement
# commands instead of silently targeting a different, stale IP from boot.
motion.set_robot_ip(ESP32_IP)
cloud_manager = CloudManager()
memory_manager = LongTermMemoryManager(persist_path="./jarvis_brain_db")

def jarvis_speak(text: str):
    global IS_SPEAKING, HARD_MUTE, IGNORE_MIC_UNTIL
    with STATE_LOCK:
        IS_SPEAKING = True
        HARD_MUTE = True
    add_log_event(f"Jarvis spoke: {text[:40]}...")
    set_esp32_emotion("happy")

    clean_speech_text = re.sub(r'<[^>]*>', '', text)
    if AudioSegment is None:
        if CURRENT_LANGUAGE == "hi" and tts_hi_local: tts_hi_local.speak(clean_speech_text)
        elif tts_en_local: tts_en_local.speak(clean_speech_text)
        with STATE_LOCK:
            IS_SPEAKING = False
            HARD_MUTE = False
            IGNORE_MIC_UNTIL = time.time() + 2.0
        return

    temp_mp3 = os.path.join(TEMP_AUDIO_DIR, f"temp_tts_{uuid.uuid4().hex}.mp3")
    try:
        tld_code = "co.in" if CURRENT_LANGUAGE == "hi" else "co.uk"
        tts = gTTS(text=clean_speech_text, lang=CURRENT_LANGUAGE, tld=tld_code)
        tts.save(temp_mp3)

        audio = AudioSegment.from_mp3(temp_mp3)
        gain_db = (SPEAKER_VOLUME_GAIN - 1.0) * 15.0
        audio = audio.set_frame_rate(16000).set_channels(2).set_sample_width(2) + gain_db
        raw_pcm_data = audio.raw_data

        ip = ESP32_IP.replace("http://", "").split(":")[0]
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        # FIX: disable Nagle's algorithm so small writes aren't delayed/coalesced
        # unpredictably by the OS, which was a source of the choppy audio.
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.connect((ip, 82))

        # FIX: previously this looped in fixed 1024-byte chunks with a manual
        # time.sleep(0.012) between every chunk AND silently dropped the final
        # partial chunk (`if len(chunk) == chunk_size`). The manual pacing
        # fights with TCP's own flow control and caused underruns on the
        # ESP32 I2S buffer (audio choppy/garbled even with motors off), and
        # the dropped tail chunk truncated/clicked at the end of every phrase.
        # sendall() lets the OS handle buffering correctly and sends 100% of
        # the audio. If your ESP32 firmware genuinely needs throttling because
        # its receive buffer is small, throttle in fixed 4-8KB blocks instead
        # of 1KB, and only add sleeps back in if you still see underruns.
        s.sendall(raw_pcm_data)
        s.close()
    except Exception as e:
        logger.error(f"Speaker Stream Error: {e}. Using local fallback.")
        if CURRENT_LANGUAGE == "hi" and tts_hi_local: tts_hi_local.speak(clean_speech_text)
        elif tts_en_local: tts_en_local.speak(clean_speech_text)
    finally:
        if os.path.exists(temp_mp3): os.remove(temp_mp3)
        time.sleep(0.3)
        with STATE_LOCK:
            IS_SPEAKING = False
            HARD_MUTE = False
            IGNORE_MIC_UNTIL = time.time() + 2.0

def capture_and_upload_snapshot() -> str:
    set_esp32_emotion("thinking")
    frame = vision_pipeline.get_latest_frame()
    if frame is None: return "Error: camera feed unavailable."

    success, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not success: return "Error: failed to encode frame."

    result_url = cloud_manager.upload_snapshot(buffer.tobytes())
    if result_url and not result_url.startswith("Error"):
        add_log_event(f"Snapshot uploaded: {result_url}")
        set_esp32_emotion("happy")
    else:
        set_esp32_emotion("confused")
    return result_url

def execute_hazard_scan() -> str:
    frame = vision_pipeline.get_latest_frame()
    if frame is None or not brain.gemini_client: return "Camera visual feed offline for hazard analysis, sir."
    try:
        set_esp32_emotion("thinking")
        success, buffer = cv2.imencode('.jpg', frame)
        if not success: return "Failed to process visual frame."
        prompt = "Analyze this robot forward-camera view for immediate navigation hazards: look for tripping hazards, floor drops, cables, tight pinch points, or obstacles in the pathway. Report status concisely in 1 or 2 sentences."
        res = brain.gemini_client.models.generate_content(model='gemini-3.6-flash', contents=[types.Part.from_bytes(data=buffer.tobytes(), mime_type='image/jpeg'), prompt])
        report = res.text.strip()
        set_esp32_emotion("happy")
        return report
    except Exception as e: return "Hazard evaluation failed to resolve telemetry."

# ==========================================
# ACOUSTIC SENTRY LOGIC
# ==========================================
def trigger_acoustic_sentry():
    """Reacts to loud, sudden noises while in autonomous patrol."""
    global AUTONOMOUS_MODE
    AUTONOMOUS_MODE = False
    send_esp32_stop(retries=2)
    set_esp32_eyes(255, 100, 0) # Orange
    trigger_esp32_beep()
    add_log_event("ACOUSTIC ALERT: Loud noise detected.")
    _notify_async("Loud/unexpected noise detected during patrol. Scanning perimeter.", title="JARVIS: Acoustic Alert")
    jarvis_speak("Acoustic anomaly detected. Scanning perimeter for threats.")
    execute_tracked_movement("left", 0.5)
    time.sleep(0.5)
    execute_tracked_movement("right", 0.5)
    time.sleep(0.5)
    report = execute_hazard_scan()
    jarvis_speak(report)

AUDIO_BUFFER = []
IS_RECORDING = False
SILENCE_START = None
SILENCE_THRESHOLD = 100
SILENCE_DURATION = 1.5
PROCESSING_AUDIO = False

WHISPER_HALLUCINATIONS = [
    "james", "thank you", "subscribe", "amara.org", "thanks for watching",
    "i await your next command", "roll reversal", "homie", "blank"
]

def process_robot_audio():
    global PROCESSING_AUDIO, WAITING_FOR_WAKE_WORD
    with STATE_LOCK:
        PROCESSING_AUDIO = True
        if len(AUDIO_BUFFER) < 20:
            AUDIO_BUFFER.clear()
            PROCESSING_AUDIO = False
            set_esp32_emotion("happy")
            return
        raw_data = b"".join(AUDIO_BUFFER)
        AUDIO_BUFFER.clear()

    set_esp32_emotion("thinking")
    temp_wav = os.path.join(TEMP_AUDIO_DIR, f"robot_mic_{uuid.uuid4().hex}.wav")
    try:
        with wave.open(temp_wav, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(raw_data)

        with open(temp_wav, "rb") as f:
            transcription = groq_client.audio.transcriptions.create(
                file=("audio.wav", f.read()),
                model="whisper-large-v3",
                language=CURRENT_LANGUAGE
            )

        user_text = transcription.text.strip()
        lower_text = user_text.lower()

        if not user_text or any(h in lower_text for h in WHISPER_HALLUCINATIONS) or len(user_text) < 3:
            set_esp32_emotion("happy")
            return

        logger.info(f"Robot Heard: {user_text}")

        if WAITING_FOR_WAKE_WORD:
            if "jarvis" in lower_text or "जारविस" in lower_text:
                add_log_event("Robot Wake-Word Triggered.")
                extracted = lower_text.replace("jarvis", "").replace("hey", "").replace(",", "").replace(".", "").strip()
                WAITING_FOR_WAKE_WORD = False
                if len(extracted) > 2: threading.Thread(target=process_command_and_speech, args=(extracted,)).start()
                else: jarvis_speak(f"Yes, {BOSS_NAME}?")
            else: set_esp32_emotion("happy")
        else:
            WAITING_FOR_WAKE_WORD = True
            threading.Thread(target=process_command_and_speech, args=(user_text,)).start()

    except Exception as e:
        logger.error(f"Robot Mic Error: {e}")
        set_esp32_emotion("confused")
    finally:
        with STATE_LOCK: PROCESSING_AUDIO = False
        if os.path.exists(temp_wav): os.remove(temp_wav)

@app.post("/api/robot_mic")
async def robot_mic_stream(request: Request):
    global IS_RECORDING, SILENCE_START, PROCESSING_AUDIO
    chunk = await request.body()
    if not chunk: return {"status": "empty"}
    audio_data = np.frombuffer(chunk, dtype=np.int16)
    rms = np.sqrt(np.mean(np.square(audio_data, dtype=np.float32)))

    if AUTONOMOUS_MODE and rms > 2500 and not IS_SPEAKING and time.time() > IGNORE_MIC_UNTIL:
        threading.Thread(target=trigger_acoustic_sentry, daemon=True).start()
        return {"status": "sentry_triggered"}

    with STATE_LOCK:
        if IS_SPEAKING or HARD_MUTE or time.time() < IGNORE_MIC_UNTIL:
            if IS_RECORDING: IS_RECORDING = False
            AUDIO_BUFFER.clear()
            return {"status": "muted"}

        if PROCESSING_AUDIO: return {"status": "busy"}

        if IS_RECORDING and len(AUDIO_BUFFER) > 150:
            IS_RECORDING = False
            SILENCE_START = None
            threading.Thread(target=process_robot_audio, daemon=True).start()
            return {"status": "ok"}

        if rms > SILENCE_THRESHOLD:
            if not IS_RECORDING:
                IS_RECORDING = True
                should_set_listening = True
            else: should_set_listening = False
            SILENCE_START = None
            AUDIO_BUFFER.append(chunk)
        elif IS_RECORDING:
            should_set_listening = False
            AUDIO_BUFFER.append(chunk)
            if SILENCE_START is None: SILENCE_START = time.time()
            elif time.time() - SILENCE_START > SILENCE_DURATION:
                IS_RECORDING = False
                SILENCE_START = None
                threading.Thread(target=process_robot_audio, daemon=True).start()
        else: should_set_listening = False

    if should_set_listening: set_esp32_emotion("listening")
    return {"status": "ok"}

def fallback_to_ollama(user_message: str, language_mode: str, memory_context: str = "", vision_context: str = "") -> str:
    url = "http://127.0.0.1:11434/api/chat"
    lang_instruction = "Respond natively in Hindi." if language_mode == "hi" else "Respond natively in English."
    try:
        response = requests.post(url, json={"model": OLLAMA_LOCAL_MODEL, "messages": [{"role": "system", "content": f"You are JARVIS, an advanced AI assistant to {BOSS_NAME}. Be concise. {lang_instruction} {memory_context} {vision_context}"}, {"role": "user", "content": f"Answer accurately in 1-2 sentences: {user_message}"}], "stream": False}, timeout=15)
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "Neural link fallback active, sir.").strip()
    except Exception as e:
        logger.error(f"Ollama Fallback Failed: {e}")
        return "Neural processors are temporarily offline, sir."

def get_groq_vision_response(user_message: str, language_mode: str = "en", is_proactive: bool = False) -> str:
    set_esp32_emotion("thinking")
    memory_context = ""
    global ACTIVE_TASK
    try:
        if not is_proactive:
            try:
                relevant_memory = memory_manager.query_memory(user_message, n_results=3)
                memory_context = f"\nRelevant Memory Context: {relevant_memory}" if relevant_memory else ""
            except Exception: pass

        frame = vision_pipeline.get_latest_frame()
        if frame is None:
            if is_proactive: return ""
            return brain.think(f"{memory_context}\nUser says: {user_message}", language_mode=language_mode, engine_preference=ROBOT_SETTINGS.get("aiEngine", "groq"))

        if brain.gemini_client:
            success, buffer = cv2.imencode('.jpg', frame)
            if success:
                instruction = "Make a concise, witty observation in 1 sentence." if is_proactive else "Concise answer in 1-2 sentences strictly grounded in visual facts."
                gemini_res = brain.gemini_client.models.generate_content(
                    model='gemini-3.6-flash',
                    contents=[types.Part.from_bytes(data=buffer.tobytes(), mime_type='image/jpeg'), f"You are JARVIS. {instruction} Query: {user_message}"]
                )
                answer = gemini_res.text.strip()
                if is_proactive: return answer
                set_esp32_emotion("happy")
                return answer

        visible = vision_pipeline.get_detected_labels()
        if visible:
            set_esp32_emotion("happy")
            return f"I can see: {', '.join(visible)}, sir."
        return "Neural processors are temporarily offline, sir."

    except Exception as e:
        logger.warning(f"Vision call error: {e}")
        visible = vision_pipeline.get_detected_labels()
        return f"I detect: {', '.join(visible)}, sir." if visible else "Sensors offline, sir."

def get_current_time():
    now = datetime.now()
    time_str = now.strftime("%I:%M %p on %A, %B %d, %Y")
    if time_str.startswith('0'): time_str = time_str[1:]
    return f"Sir, the current time is {time_str}."

def get_weather_and_location():
    try:
        loc_res = requests.get("http://ip-api.com/json/", timeout=5).json()
        city = loc_res.get("city", "your city")
        lat, lon = loc_res.get("lat"), loc_res.get("lon")
        weather_res = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true", timeout=5).json()
        temp = weather_res["current_weather"]["temperature"]
        wind = weather_res["current_weather"]["windspeed"]
        return f"Sir, I have located us in {city}. Temperature: {temp}°C, Wind Speed: {wind} km/h."
    except: return "I am currently unable to access the global weather grid, sir."

def get_daily_news(user_query: str = ""):
    news_key = os.getenv("NEWS_API_KEY", "")
    if not news_key: return "Sir, the News API module is offline."
    q_low = user_query.lower()
    urls = [f"https://newsapi.org/v2/top-headlines?country=in&apiKey={news_key}"] if "india" in q_low else []
    urls += [f"https://newsapi.org/v2/top-headlines?language=en&apiKey={news_key}", f"https://newsapi.org/v2/everything?q=technology&sortBy=publishedAt&apiKey={news_key}"]

    articles = []
    for u in urls:
        try:
            res = requests.get(u, timeout=5).json()
            if res.get("articles"):
                articles = res["articles"][:3]
                break
        except: pass

    if not articles: return "There are no significant news updates at this time, sir."
    news_text = "Here are the top headlines: "
    for i, art in enumerate(articles):
        news_text += f"Headline {i+1}: {art.get('title', '').split('-')[0].strip()}. "
    return news_text + "That concludes the briefing, sir."

# NEW: words/phrases that trigger a follow/track command generically.
FOLLOW_VERBS = ["follow", "track", "chase", "trail"]
STOP_FOLLOW_PHRASES = ["stop following", "cancel follow", "unfollow", "stop tracking", "stop trailing"]
GOTO_VERBS = ["go to", "go there", "navigate to", "head to", "move to", "drive to", "go towards", "go where"]
FILLER_WORDS = {"please", "now", "sir", "the", "a", "an", "over", "there", "to", "towards"}

def _extract_follow_target(user_intent: str) -> str:
    """Pulls the object phrase out of e.g. 'follow the chair' -> 'chair'."""
    text = user_intent
    for verb in FOLLOW_VERBS:
        if verb in text:
            text = text.split(verb, 1)[1]
            break
    tokens = [w for w in re.findall(r"[a-zA-Z']+", text) if w not in FILLER_WORDS]
    # "follow me" / "follow my lead" -> person
    if not tokens or tokens[0] in ("me", "my", "us"):
        return "person"
    return " ".join(tokens).strip()

def _extract_goto_target(user_intent: str) -> str:
    text = user_intent
    for verb in GOTO_VERBS:
        if verb in text:
            text = text.split(verb, 1)[1]
            break
    tokens = [w for w in re.findall(r"[a-zA-Z']+", text) if w not in FILLER_WORDS]
    return " ".join(tokens).strip()

def process_command_and_speech(user_message: str) -> str:
    global AUTONOMOUS_MODE, FOLLOW_ME_MODE, COLOR_HUNT_MODE, COLOR_HUNT_TARGET, GESTURE_MODE, FOLLOW_TARGET_LABEL
    try:
        user_intent = user_message.lower()

        if any(w in user_intent for w in ["good morning", "good afternoon", "good evening", "morning briefing", "daily briefing"]):
            current_hour = datetime.now().hour

            if current_hour < 12: actual_time_of_day = "morning"
            elif current_hour < 17: actual_time_of_day = "afternoon"
            else: actual_time_of_day = "evening"

            greeting = f"Good {actual_time_of_day}, Meet."

            if "morning" in user_intent and actual_time_of_day != "morning":
                greeting = f"Actually sir, it is currently the {actual_time_of_day}, but I will initialize your briefing anyway."
            elif "afternoon" in user_intent and actual_time_of_day != "afternoon":
                greeting = f"Actually sir, it is currently the {actual_time_of_day}. Initializing your briefing."
            elif "evening" in user_intent and actual_time_of_day != "evening":
                greeting = f"Actually sir, it is currently the {actual_time_of_day}. Initializing your briefing."

            jarvis_speak(greeting)
            set_esp32_eyes(0, 191, 255)
            execute_tracked_movement("left", 0.6)
            time.sleep(0.3)
            execute_tracked_movement("right", 0.6)

            weather = get_weather_and_location()
            news = get_daily_news("India")

            try:
                reminders = memory_manager.query_memory("What are my current projects, tasks, or reminders?", n_results=2)
                reminder_txt = f"Neural link records: {reminders}" if reminders else "No specific tasks found in memory."
            except:
                reminder_txt = "Memory link offline."

            briefing_prompt = (
                f"Please summarize my daily briefing naturally in 3-4 sentences. "
                f"DO NOT recite raw database logs like 'User asked' or 'Jarvis answered'. "
                f"Just tell me the facts smoothly.\n\n"
                f"Weather: {weather}\nNews: {news}\nMemories: {reminder_txt}"
            )

            final_briefing = brain.think(briefing_prompt, language_mode=CURRENT_LANGUAGE, engine_preference=ROBOT_SETTINGS.get("aiEngine", "groq"))
            clean_briefing = re.sub(r'<[^>]*>', '', final_briefing)

            for sentence in re.split(r'(?<=[.!?])\s+', clean_briefing):
                if sentence.strip(): jarvis_speak(sentence.strip())

            return clean_briefing

        if any(w in user_intent for w in ["hand gestures", "gesture mode", "optical navigation"]):
            AUTONOMOUS_MODE = False
            FOLLOW_ME_MODE = False
            COLOR_HUNT_MODE = False
            GESTURE_MODE = True
            msg = "Optical hand-gesture navigation engaged. I am watching your hands, sir."
            jarvis_speak(msg)
            set_esp32_eyes(153, 50, 204)
            return msg

        if any(w in user_intent for w in ["stop gestures", "cancel gestures"]):
            GESTURE_MODE = False
            send_esp32_stop(retries=2)
            msg = "Gesture navigation disengaged."
            jarvis_speak(msg)
            return msg

        # ---- STOP FOLLOW (must be checked before the generic follow match) ----
        if any(p in user_intent for p in STOP_FOLLOW_PHRASES):
            FOLLOW_ME_MODE = False
            send_esp32_stop(retries=2)
            msg = "Follow protocol disengaged."
            jarvis_speak(msg)
            return msg

        # ---- GENERIC FOLLOW / TRACK <anything> ----
        # FIX: previously only the exact phrases "follow me" / "track me" /
        # "follow my lead" were recognized. Anything else (e.g. "follow the
        # chair") fell through to the language model, which just spoke a
        # made-up confirmation without ever engaging FOLLOW_ME_MODE — so the
        # robot never actually moved. This now catches any "follow/track/
        # chase <object>" phrasing and engages real tracking against that
        # object label (or the person, for "follow me").
        if any(v in user_intent for v in FOLLOW_VERBS):
            target_label = _extract_follow_target(user_intent)
            AUTONOMOUS_MODE = False
            COLOR_HUNT_MODE = False
            GESTURE_MODE = False
            FOLLOW_ME_MODE = True
            with STATE_LOCK:
                FOLLOW_TARGET_LABEL = target_label
            display_target = "you" if target_label == "person" else target_label
            if not hasattr(vision_pipeline, "get_object_bbox") and target_label != "person":
                msg = (f"Visual tracking protocol engaged for {display_target}, sir, "
                       f"but my object-detection module does not yet support arbitrary "
                       f"labels — I can currently only lock onto people.")
            else:
                msg = f"Visual tracking protocol engaged. Locking onto target: {display_target}, sir."
            jarvis_speak(msg)
            set_esp32_eyes(0, 255, 204)
            return msg

        # ---- GENERIC GO TO / NAVIGATE TO <object> ----
        # FIX: "go to the red object" / "go there" previously only spoke a
        # canned confirmation and never drove anywhere. This now actually
        # drives the robot toward the target using live vision feedback.
        if any(v in user_intent for v in GOTO_VERBS) or ("come here" not in user_intent and "come back" not in user_intent and "return to base" not in user_intent and "go" in user_intent and ("object" in user_intent or "there" in user_intent)):
            target_label = _extract_goto_target(user_intent)
            if not target_label:
                target_label = COLOR_HUNT_TARGET if COLOR_HUNT_MODE or "object" in user_intent else "person"
            use_color = target_label in ["red", "green", "blue", "yellow"]
            msg = f"Understood, sir. Navigating to the {target_label} now."
            jarvis_speak(msg)
            threading.Thread(target=navigate_to_target_object, args=(target_label, use_color), daemon=True).start()
            return msg

        if "find the" in user_intent and "object" in user_intent or "hunt" in user_intent:
            for color in ["red", "green", "blue", "yellow"]:
                if color in user_intent:
                    COLOR_HUNT_TARGET = color
                    AUTONOMOUS_MODE = False
                    FOLLOW_ME_MODE = False
                    GESTURE_MODE = False
                    COLOR_HUNT_MODE = True
                    msg = f"Targeting {color} visual signature. Initiating hunt protocol."
                    jarvis_speak(msg)
                    return msg

        # ---- REMINDERS ----
        if "remind me" in user_intent or "set a reminder" in user_intent:
            due = _parse_reminder_datetime(user_intent)
            if not due:
                msg = "I couldn't figure out the timing for that. Try 'remind me to take medicine in 20 minutes', 'after 5 minutes', or 'at 6pm'."
                jarvis_speak(msg)
                return msg
            task_text = _extract_reminder_text(user_message)
            reminder = add_reminder(task_text, due)
            when_str = due.strftime("%I:%M %p")
            msg = f"Got it. I'll remind you to {reminder['text']} at {when_str}."
            jarvis_speak(msg)
            return msg

        if any(w in user_intent for w in ["list my reminders", "what are my reminders", "show reminders", "upcoming reminders"]):
            with REMINDERS_LOCK:
                pending = sorted([r for r in REMINDERS if not r.get("done")], key=lambda r: r["due_ts"])
            if not pending:
                msg = "You have no active reminders, sir."
            else:
                parts = [f"{r['text']} at {datetime.fromtimestamp(r['due_ts']).strftime('%I:%M %p')}" for r in pending[:5]]
                msg = "Here are your upcoming reminders: " + "; ".join(parts) + "."
            jarvis_speak(msg)
            return msg

        if any(w in user_intent for w in ["cancel my reminder", "delete reminder", "cancel reminder"]):
            with REMINDERS_LOCK:
                pending = sorted([r for r in REMINDERS if not r.get("done")], key=lambda r: r["due_ts"])
                if pending:
                    removed = pending[0]
                    REMINDERS.remove(removed)
                    save_reminders_to_disk()
                    msg = f"Cancelled reminder: {removed['text']}."
                else:
                    msg = "You have no active reminders to cancel, sir."
            jarvis_speak(msg)
            return msg

        # ---- REAL ALERTING ----
        if any(w in user_intent for w in ["test alert", "test notification", "send test alert"]):
            results = notifier.notify_emergency("This is a test alert from JARVIS.", title="JARVIS: Test Alert", priority="default")
            channels_ok = [k for k, v in results.items() if v]
            msg = f"Test alert sent via {', '.join(channels_ok)}." if channels_ok else "Test alert failed on all channels. Check TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID or NTFY_TOPIC in your .env file."
            jarvis_speak(msg)
            return msg

        if any(w in user_intent for w in ["emergency", "i need help", "call for help", "sos"]):
            notifier.notify_emergency("Manual emergency trigger activated by voice command.", title="JARVIS: SOS TRIGGERED")
            add_log_event("MANUAL SOS TRIGGERED")
            msg = "Emergency alert sent, sir."
            jarvis_speak(msg)
            return msg

        if any(w in user_intent for w in ["hazard", "scan for hazards", "path clearance"]):
            jarvis_speak("Scanning optical path for navigational hazards.")
            # NEW: previously this did zero movement -- just analyzed the
            # current camera angle. Added a short sweep so "scan" actually
            # looks around, matching what "scan the room" already does.
            execute_tracked_movement("left", 0.4)
            time.sleep(0.2)
            execute_tracked_movement("right", 0.4)
            time.sleep(0.2)
            execute_tracked_movement("stop", 0.0)
            report = execute_hazard_scan()
            jarvis_speak(report)
            return report

        if any(w in user_intent for w in ["scan the room", "what do you see", "what is in front"]):
            jarvis_speak("Initiating perimeter visual scan.")
            execute_tracked_movement("left", 0.8)
            time.sleep(0.4)
            execute_tracked_movement("right", 0.8)
            time.sleep(0.4)
            execute_tracked_movement("stop", 0.0)
            scan_summary = get_groq_vision_response(user_message, language_mode=CURRENT_LANGUAGE)
            jarvis_speak(scan_summary)
            return scan_summary

        if any(w in user_intent for w in ["take a snapshot", "take a photo", "take a picture"]):
            jarvis_speak("Capturing security snapshot.")
            threading.Thread(target=capture_and_upload_snapshot, daemon=True).start()
            return "Taking snapshot."

        if "come here" in user_intent or "come back" in user_intent or "return to base" in user_intent:
            threading.Thread(target=reverse_path).start()
            return "Reversing path coordinates."

        creator_keywords = ["who made you", "who created you", "who built you", "team members", "your creators", "group 7", "group no 7"]
        if any(kw in user_intent for kw in creator_keywords):
            intro = "I was engineered by Group No. 7 under the expert guidance of Prof. P. V. Gupta Ma'am."
            jarvis_speak(intro)
            try: requests.get(f"{ESP32_IP}/team?server={LAN_SERVER_ADDRESS}", timeout=1.0)
            except Exception: pass
            threading.Thread(target=speak_team_introductions, daemon=True).start()
            return intro

        if any(w in user_intent for w in ["stop", "halt", "रुको", "ruko"]):
            force_stop_all()
            msg = "सिस्टम रोक दिया गया है।" if CURRENT_LANGUAGE == "hi" else "All systems halted, sir."
            jarvis_speak(msg)
            return msg

        if any(w in user_intent for w in ["start autonomy", "patrol", "wander"]):
            # FIX: previously this flipped AUTONOMOUS_MODE = True unconditionally.
            # If the ESP32 motor controller is unreachable (as in your logs —
            # repeated "Connection timed out" on 10.101.240.52), every movement
            # silently failed and it just *looked* like autonomous mode "wasn't
            # working". Now Jarvis checks reachability first and tells you.
            if not check_esp32_online():
                msg = "I cannot reach my motor controller right now, sir. Please check the robot's WiFi connection before I can patrol."
                jarvis_speak(msg)
                add_log_event("AUTONOMY START FAILED: ESP32 unreachable.")
                return msg
            AUTONOMOUS_MODE = True
            FOLLOW_ME_MODE = False
            COLOR_HUNT_MODE = False
            GESTURE_MODE = False
            msg = "Autonomous perimeter patrol protocol activated, sir."
            jarvis_speak(msg)
            return msg

        movement_dict = {
            "forward left": "forward_left", "forward right": "forward_right",
            "aage badho": "forward", "aage": "forward", "आगे": "forward", "forward": "forward",
            "peeche": "backward", "पीछे": "backward", "backward": "backward", "back": "backward",
            "baayen": "left", "बाएं": "left", "left": "left",
            "daayen": "right", "दाएं": "right", "right": "right"
        }

        matched_movement = None
        for key, val in movement_dict.items():
            if key in user_intent:
                matched_movement = val
                break

        if matched_movement and len(user_intent.split()) <= 4 and "?" not in user_intent:
            AUTONOMOUS_MODE = False
            FOLLOW_ME_MODE = False
            COLOR_HUNT_MODE = False
            GESTURE_MODE = False
            dur = 1.5 if "forward" in matched_movement else 0.8
            execute_tracked_movement(matched_movement, dur)
            msg = "निर्देश का पालन कर रहा हूँ।" if CURRENT_LANGUAGE == "hi" else f"Executing {matched_movement}."
            jarvis_speak(msg)
            return msg

        response_text = brain.think(user_message, language_mode=CURRENT_LANGUAGE, engine_preference=ROBOT_SETTINGS.get("aiEngine", "groq"))
        add_log_event("AI response generated")
        jarvis_speak(response_text)
        return response_text

    except Exception as e:
        logger.error(f"Error in command execution: {e}")
        return "Error processing command."

# ==========================================
# BACKGROUND CLOSED-LOOP THREADS
# ==========================================

def battery_monitor_loop():
    logger.info("Critical Battery Monitor online.")
    warned = False
    while True:
        uptime_seconds = time.time() - SYSTEM_BOOT_TIME
        drain_rate_per_sec = (100.0 / (5.0 * 3600.0))
        battery = max(5, int(100 - (uptime_seconds * drain_rate_per_sec)))

        if battery <= 20 and not warned:
            jarvis_speak("Warning, Meet. Power reserves have dropped below 20 percent. Please connect the main charging terminal.")
            add_log_event("BATTERY WARNING: Dropped below 20%.")
            _notify_async("Battery reserves below 20%. Please recharge soon.", title="JARVIS: Low Battery", priority="high")
            set_esp32_eyes(255, 0, 0)
            warned = True

        time.sleep(60)

def gesture_loop():
    global GESTURE_MODE
    logger.info("Gesture Navigation loop online.")
    last_gesture_sent = None
    while True:
        try:
            if GESTURE_MODE:
                frame = vision_pipeline.get_latest_frame()
                gesture = gesture_navigator.detect_gesture(frame)

                # FIX: previously every tick called execute_tracked_movement(),
                # which BLOCKS for the pulse duration (0.2-0.3s) then
                # explicitly sends an auto-stop right after. Given your ESP32
                # link's frequent multi-hundred-ms to multi-second latency
                # (seen throughout your logs), that trailing stop could land
                # almost immediately after -- or even overlapping -- the move
                # command, so motors barely twitch or don't visibly move at
                # all. This now sends a plain hold-until-changed command
                # (same pattern the dashboard D-pad already uses
                # successfully) and only fires a new HTTP call when the
                # direction actually changes, instead of spamming one every
                # ~150ms regardless of whether it's needed.
                target_dir = None
                if gesture == "forward": target_dir = "forward"
                elif gesture == "left": target_dir = "left"
                elif gesture == "right": target_dir = "right"
                elif gesture == "stop": target_dir = "stop"

                if target_dir and target_dir != last_gesture_sent:
                    try:
                        requests.get(f"{ESP32_IP}/move?dir={target_dir}", timeout=1.0)
                    except Exception as e:
                        logger.error(f"Gesture move command failed: {e}")
                    last_gesture_sent = target_dir
                elif gesture == "none" and last_gesture_sent not in (None, "stop"):
                    # hand left frame / unrecognized shape -- stop rather
                    # than keep driving blind on a stale command.
                    send_esp32_stop(retries=1)
                    last_gesture_sent = "stop"

                time.sleep(0.12)
            else:
                if last_gesture_sent not in (None, "stop"):
                    send_esp32_stop(retries=1)
                    last_gesture_sent = None
                time.sleep(0.4)
        except Exception as e:
            logger.error(f"Gesture loop error: {e}")
            time.sleep(0.5)

def follow_me_loop():
    global FOLLOW_ME_MODE, FOLLOW_TARGET_LABEL
    logger.info("Visual Follow-Me closed-loop tracker online.")
    while True:
        try:
            if FOLLOW_ME_MODE:
                frame = vision_pipeline.get_latest_frame()

                with STATE_LOCK:
                    target_label = FOLLOW_TARGET_LABEL

                # FIX: previously this loop always called get_person_bbox(),
                # ignoring whatever object was actually requested. Now it tracks
                # the requested label; falls back to person-tracking if the
                # vision pipeline has no generic object-bbox support yet.
                if target_label in ("person", "me", "you") or not hasattr(vision_pipeline, "get_object_bbox"):
                    target = vision_pipeline.get_person_bbox()
                else:
                    target = vision_pipeline.get_object_bbox(target_label)

                if frame is not None and target:
                    frame_w = frame.shape[1]
                    offset_x = target["center_x"] - (frame_w / 2.0)
                    dist = get_distance_safe()

                    if offset_x < -75: execute_tracked_movement("left", 0.15)
                    elif offset_x > 75: execute_tracked_movement("right", 0.15)
                    else:
                        if dist > 65: execute_tracked_movement("forward", 0.25)
                        elif 0 < dist < 35: execute_tracked_movement("backward", 0.2)
                        else: send_esp32_stop(retries=1)
                else: send_esp32_stop(retries=1)
                time.sleep(0.1)
            else: time.sleep(0.4)
        except Exception as e:
            logger.error(f"Follow-me loop error: {e}")
            time.sleep(0.5)

def color_hunt_loop():
    global COLOR_HUNT_MODE, COLOR_HUNT_TARGET
    while True:
        try:
            if COLOR_HUNT_MODE:
                data = vision_pipeline.get_dominant_color_direction(COLOR_HUNT_TARGET)
                dist = get_distance_safe()

                if data["found"]:
                    direction = data["direction"]
                    if direction == "left": execute_tracked_movement("left", 0.18)
                    elif direction == "right": execute_tracked_movement("right", 0.18)
                    elif direction == "center":
                        if dist > 35: execute_tracked_movement("forward", 0.25)
                        else:
                            send_esp32_stop(retries=2)
                            jarvis_speak(f"Reached {COLOR_HUNT_TARGET} visual objective, sir.")
                            COLOR_HUNT_MODE = False
                else: execute_tracked_movement("right", 0.2)
                time.sleep(0.12)
            else: time.sleep(0.4)
        except Exception as e:
            logger.error(f"Color-hunt loop error: {e}")
            time.sleep(0.5)

def autonomous_navigation_loop():
    global AUTONOMOUS_MODE, WAITING_FOR_WAKE_WORD, WAKE_WORD_TRIGGER_TIME, IS_SPEAKING
    logger.info("Autonomous Living AI & Sentry Loop online.")
    last_comment_time = time.time()
    sentry_cooldown = 0.0
    last_offline_warning = 0.0

    while True:
        if not WAITING_FOR_WAKE_WORD and (time.time() - WAKE_WORD_TRIGGER_TIME > 6.0) and not IS_SPEAKING:
            WAITING_FOR_WAKE_WORD = True
            set_esp32_emotion("happy")
            set_esp32_eyes(0, 255, 204)

        if AUTONOMOUS_MODE:
            try:
                now = time.time()

                # FIX: if the ESP32 becomes unreachable mid-patrol, don't just
                # keep silently failing every move call forever — warn once
                # every 60s so it's obvious this is a connectivity issue.
                if not check_esp32_online(timeout=0.6):
                    if now - last_offline_warning > 60.0:
                        add_log_event("AUTONOMY WARNING: Motor controller unreachable.")
                        last_offline_warning = now
                    time.sleep(1.0)
                    continue

                distance = get_distance_safe()
                person = vision_pipeline.get_person_bbox()

                if person and (now - sentry_cooldown > 30.0):
                    send_esp32_stop(retries=2)
                    set_esp32_eyes(255, 0, 0)
                    trigger_esp32_beep()
                    add_log_event("SENTRY ALERT: Human subject detected in patrol perimeter.")
                    _notify_async("Human subject detected during autonomous patrol. Snapshot captured.", title="JARVIS: Intruder Alert")
                    threading.Thread(target=capture_and_upload_snapshot, daemon=True).start()
                    jarvis_speak("Security alert. Human subject identified within patrol perimeter.")
                    sentry_cooldown = now
                    time.sleep(2.0)
                    continue

                if 0 < distance < 30:
                    set_esp32_emotion("surprise")
                    execute_tracked_movement("backward", 0.6)
                    execute_tracked_movement(random.choice(["left", "right"]), 0.6)
                elif now - last_comment_time > 60:
                    visible_labels = vision_pipeline.get_detected_labels()
                    memory_injection = ""
                    if visible_labels:
                        try:
                            context = memory_manager.query_memory(f"What do we know about {', '.join(visible_labels)}?", n_results=1)
                            if context and len(context) > 10:
                                memory_injection = f"Neural link context: {context}. "
                        except Exception: pass

                    if memory_injection:
                        prompt = f"{memory_injection}Make a single, short 1-sentence observation stating that you recognize this location or object based on the neural link context."
                    else:
                        prompt = "Make a single, short, witty 1-sentence observation about your surroundings."

                    obs = get_groq_vision_response(prompt, is_proactive=True)
                    if obs: jarvis_speak(obs)
                    last_comment_time = now
                else:
                    move_choice = random.choices(["forward", "left", "right"], weights=[0.8, 0.1, 0.1])[0]
                    dur = 0.4 if move_choice == "forward" else 0.2
                    execute_tracked_movement(move_choice, dur)

            except Exception as e:
                logger.error(f"Autonomy loop error: {e}")
                time.sleep(1.0)
        time.sleep(0.3)

def register_server_with_esp32():
    if not ESP32_IP: return
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('10.255.255.255', 1))
            laptop_ip = s.getsockname()[0]
            s.close()
            url = f"{ESP32_IP}/set_server?ip={laptop_ip}"
            response = requests.get(url, timeout=1.5)
            if response.status_code == 200: break
        except: pass
        time.sleep(10)

def play_boot_sequence():
    try:
        time.sleep(2.5)
        set_esp32_emotion("happy")
        set_esp32_eyes(0, 255, 204)
        add_log_event("JARVIS Core Boot Sequence Complete")
        jarvis_speak(f"Systems online, sir. All neural links and visual sensors initialized. Awaiting your command, {BOSS_NAME}.")
    except Exception as e:
        logger.error(f"Boot Sequence Error: {e}")

class ControlCommand(BaseModel): command: str = "unknown"
class ChatRequest(BaseModel): message: str; language: str = "en"
class MoveRequest(BaseModel): direction: str; duration: float = 1.0
class VolumeRequest(BaseModel): volume_percent: int
class AutonomyRequest(BaseModel): enabled: bool
class LanguageRequest(BaseModel): language: str
class MemoryRequest(BaseModel): text: str
class EyeColorRequest(BaseModel): hex_color: str
class ReminderRequest(BaseModel):
    text: str
    due_in_minutes: int = None
    due_at_iso: str = None  # e.g. "2026-09-10T18:30:00"
    recurring: str = None   # None | "daily" | "weekly"
class SettingsRequest(BaseModel):
    robotName: str = "JARVIS MINI"
    robotIp: str = ""
    robotPort: str = ""
    # FIX: the frontend (settings.html) posts these fields too, but the
    # model previously didn't declare them, so FastAPI/Pydantic silently
    # dropped them from `req` -- aiEngine/baseSpeed/wakeWordEnabled were
    # never actually received by the handler.
    cameraIp: str = ""
    aiEngine: str = "groq"
    baseSpeed: int = 180
    wakeWordEnabled: bool = True

@app.get("/video_feed")
def video_feed(): return StreamingResponse(vision_pipeline.generate_mjpeg_stream(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/manifest.json")
async def serve_manifest(): return FileResponse(os.path.join(STATIC_DIR, "manifest.json"))

@app.get("/service-worker.js")
async def serve_sw(): return FileResponse(os.path.join(STATIC_DIR, "service-worker.js"))

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request): return templates.TemplateResponse(request=request, name="Dashboard.html", context={"active_page": "dashboard", "api_token": API_AUTH_TOKEN})

@app.get("/Camera", response_class=HTMLResponse)
async def camera(request: Request): return templates.TemplateResponse(request=request, name="Camera.html", context={"active_page": "camera"})

@app.get("/Security", response_class=HTMLResponse)
async def security_page(request: Request): return templates.TemplateResponse(request=request, name="Security.html", context={"active_page": "security", "api_token": API_AUTH_TOKEN})

@app.get("/Memory", response_class=HTMLResponse)
async def memory_page(request: Request): return templates.TemplateResponse(request=request, name="Memory.html", context={"active_page": "memory"})

@app.get("/Controls", response_class=HTMLResponse)
async def controls(request: Request): return templates.TemplateResponse(request=request, name="Controls.html", context={"active_page": "controls"})

@app.get("/System", response_class=HTMLResponse)
async def system(request: Request): return templates.TemplateResponse(request=request, name="System.html", context={"active_page": "system"})

@app.get("/settings", response_class=HTMLResponse)
async def settings(request: Request): return templates.TemplateResponse(request=request, name="Settings.html", context={"active_page": "settings"})

@app.get("/voice_assistant", response_class=HTMLResponse)
async def voice_assistant(request: Request): return templates.TemplateResponse(request=request, name="Voice assistant.html", context={"active_page": "voice-assistant"})

@app.get("/logs", response_class=HTMLResponse)
async def logs(request: Request): return templates.TemplateResponse(request=request, name="Logs.html", context={"active_page": "logs"})

@app.get("/api/settings")
async def api_get_settings():
    # NEW: this route didn't exist before, so settings.html's loadSettings()
    # always failed and the page just showed hardcoded blank/default HTML.
    return {"status": "success", "settings": ROBOT_SETTINGS}

@app.post("/api/settings")
async def api_save_settings(req: SettingsRequest):
    global ESP32_IP, ROBOT_SETTINGS, WAKE_WORD_ENABLED
    # FIX: previously this handler only logged the robot name and returned
    # {"status": "success"} without storing or applying ANYTHING. The
    # "Save Configuration" button looked like it worked but changed nothing
    # -- not even the robot IP, which was the one field most likely to
    # actually need changing given your ESP32 connectivity issues.

    new_motor_ip = req.robotIp.strip()
    if new_motor_ip:
        ESP32_IP = new_motor_ip if new_motor_ip.startswith("http") else f"http://{new_motor_ip}"
        # FIX: this was the missing half of the sync -- previously only
        # app.py's own ESP32_IP global got updated here. MotionController
        # kept using whatever IP it was constructed with, forever, so
        # get_distance() (and execute_movement()/execute_eye_color() if
        # ever called directly) would keep silently failing against the
        # OLD address after you changed it here.
        motion.set_robot_ip(ESP32_IP)

    new_camera_ip = req.cameraIp.strip()
    if new_camera_ip and hasattr(vision_pipeline, "stream_url"):
        stream_url = new_camera_ip if new_camera_ip.startswith("http") else f"http://{new_camera_ip}"
        if not stream_url.rstrip("/").endswith("/stream"):
            stream_url = stream_url.rstrip("/") + "/stream"
        vision_pipeline.stream_url = stream_url
        add_log_event(f"Camera stream IP updated to: {stream_url}")

    WAKE_WORD_ENABLED = req.wakeWordEnabled

    ROBOT_SETTINGS = {
        "robotName": req.robotName.strip() or ROBOT_SETTINGS.get("robotName", "JARVIS MINI"),
        "robotIp": new_motor_ip or ROBOT_SETTINGS.get("robotIp", ""),
        "cameraIp": new_camera_ip or ROBOT_SETTINGS.get("cameraIp", ""),
        "aiEngine": req.aiEngine,
        "baseSpeed": req.baseSpeed,
        "wakeWordEnabled": req.wakeWordEnabled,
    }
    save_settings_to_disk(ROBOT_SETTINGS)
    add_log_event(f"Settings saved: name={ROBOT_SETTINGS['robotName']} motor_ip={ESP32_IP}")
    return {"status": "success", "settings": ROBOT_SETTINGS}

@app.post("/api/volume")
def api_set_volume(req: VolumeRequest):
    global SPEAKER_VOLUME_GAIN
    SPEAKER_VOLUME_GAIN = max(0.0, min(2.0, req.volume_percent / 50.0))
    add_log_event(f"Speaker volume set to {req.volume_percent}%")
    return {"status": "success", "volume_percent": req.volume_percent}

# NEW: this route was missing (your logs show POST /api/language -> 404).
@app.post("/api/language")
async def api_set_language(req: LanguageRequest):
    global CURRENT_LANGUAGE
    CURRENT_LANGUAGE = req.language
    add_log_event(f"Language set to: {req.language}")
    return {"status": "success", "language": CURRENT_LANGUAGE}

@app.get("/api/robot-status")
async def api_robot_status():
    uptime_seconds = time.time() - SYSTEM_BOOT_TIME
    drain_rate_per_sec = (100.0 / (5.0 * 3600.0))
    battery_level_estimate = max(5, int(100 - (uptime_seconds * drain_rate_per_sec)))

    robot_online = check_esp32_online(timeout=0.8)

    return {
        "mode": "Hand Gestures" if GESTURE_MODE else ("Follow Me" if FOLLOW_ME_MODE else ("Color Hunt" if COLOR_HUNT_MODE else ("Autonomous" if AUTONOMOUS_MODE else "Manual"))),
        "follow_target": FOLLOW_TARGET_LABEL if FOLLOW_ME_MODE else None,
        "battery_percent": battery_level_estimate,
        "battery_is_estimated": True,
        "speed": 0.6 if (AUTONOMOUS_MODE or FOLLOW_ME_MODE or COLOR_HUNT_MODE or GESTURE_MODE) else 0.0,
        "uptime_seconds": int(uptime_seconds),
        "robot_online": robot_online
    }

@app.get("/api/snapshots")
async def api_snapshots():
    loop = asyncio.get_running_loop()
    snapshots = await loop.run_in_executor(executor, lambda: cloud_manager.get_latest_snapshots(limit=24))
    return {"status": "success", "snapshots": snapshots}

@app.delete("/api/snapshots/{public_id:path}", dependencies=[Depends(require_api_auth)])
async def api_delete_snapshot(public_id: str):
    loop = asyncio.get_running_loop()
    success = await loop.run_in_executor(executor, lambda: cloud_manager.delete_snapshot(public_id))
    if success:
        add_log_event(f"Snapshot deleted: {public_id}")
        return {"status": "success", "deleted": public_id}
    return JSONResponse(status_code=500, content={"status": "error", "message": "Failed to delete snapshot."})

@app.get("/api/memory")
async def api_get_memory():
    return {"status": "success", "memories": memory_manager.get_all_memories()}

@app.post("/api/memory", dependencies=[Depends(require_api_auth)])
async def api_add_memory(req: MemoryRequest):
    doc_id = f"mem_manual_{uuid.uuid4().hex[:8]}"
    memory_manager.add_memory(doc_id=doc_id, text_content=req.text, metadata={"source": "manual_entry", "timestamp": time.time()})
    add_log_event("Manual memory injected into Neural Link.")
    return {"status": "success", "id": doc_id}

@app.delete("/api/memory/{doc_id}", dependencies=[Depends(require_api_auth)])
async def api_delete_memory(doc_id: str):
    success = memory_manager.delete_memory(doc_id)
    return {"status": "success" if success else "error"}

@app.get("/api/sensor-data")
async def api_sensor_data():
    front_dist = 120
    try:
        loop = asyncio.get_running_loop()
        front_dist = await asyncio.wait_for(loop.run_in_executor(executor, motion.get_distance), timeout=0.4)
    except: front_dist = 120
    return {"ultrasonic_cm": {"front": front_dist}}

@app.get("/api/system-stats")
async def api_system_stats():
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": psutil.virtual_memory().percent,
        "network": {"status": "Connected", "latency_ms": random.randint(10, 25)},
        "storage_percent": psutil.disk_usage('/').percent
    }

@app.get("/api/activity-log")
async def api_activity_log(): return ACTIVITY_LOGS

@app.post("/api/control", dependencies=[Depends(require_api_auth)])
async def api_control(payload: ControlCommand):
    global AUTONOMOUS_MODE, FOLLOW_ME_MODE, COLOR_HUNT_MODE, GESTURE_MODE
    cmd = payload.command
    add_log_event(f"Dashboard control: {cmd}")

    if cmd in ["forward", "backward", "left", "right", "stop"]:
        AUTONOMOUS_MODE = False
        FOLLOW_ME_MODE = False
        COLOR_HUNT_MODE = False
        GESTURE_MODE = False
        if cmd == "stop": force_stop_all()
        else: threading.Thread(target=execute_tracked_movement, args=(cmd, 1.0), daemon=True).start()
    elif cmd == "screenshot":
        threading.Thread(target=capture_and_upload_snapshot, daemon=True).start()
    elif cmd == "autonomy_start":
        if not check_esp32_online():
            add_log_event("AUTONOMY START FAILED: ESP32 unreachable.")
            jarvis_speak("I cannot reach my motor controller right now, sir.")
            return {"status": "error", "received_command": payload.command, "reason": "esp32_unreachable"}
        AUTONOMOUS_MODE = True
        FOLLOW_ME_MODE = False
        COLOR_HUNT_MODE = False
        GESTURE_MODE = False
        jarvis_speak("Autonomous wander protocol activated, sir.")
    elif cmd == "autonomy_stop":
        force_stop_all()
        jarvis_speak("Autonomous mode disabled.")

    return {"status": "ok", "received_command": payload.command}

@app.get("/api/cast-team")
def cast_team_api(server: str = None):
    try:
        res = requests.get(f"{ESP32_IP}/team?server={LAN_SERVER_ADDRESS}", timeout=1.5)
        threading.Thread(target=speak_team_introductions, daemon=True).start()
        return {"status": "success", "esp32_response": res.text}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "error", "message": "ESP32 offline."})

@app.get("/api/cast-member")
def cast_member_api(file: str, name: str, role: str):
    try:
        url = f"{ESP32_IP}/show_member?server={LAN_SERVER_ADDRESS}&file={file}&name={name}&role={role}"
        res = requests.get(url, timeout=1.5)
        threading.Thread(target=jarvis_speak, args=(f"{name}. {role}.",), daemon=True).start()
        return {"status": "success", "esp32_response": res.text}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "error", "message": "ESP32 offline."})

@app.get("/api/move", dependencies=[Depends(require_api_auth)])
def api_move_get(dir: str = "stop", duration: float = 1.0):
    global AUTONOMOUS_MODE, FOLLOW_ME_MODE, COLOR_HUNT_MODE, GESTURE_MODE
    AUTONOMOUS_MODE = False
    FOLLOW_ME_MODE = False
    COLOR_HUNT_MODE = False
    GESTURE_MODE = False
    try:
        execute_tracked_movement(dir, duration)
        return {"status": "success", "result": True}
    except:
        return {"status": "success", "result": False}

@app.post("/api/move", dependencies=[Depends(require_api_auth)])
def api_move(req: MoveRequest):
    global AUTONOMOUS_MODE, FOLLOW_ME_MODE, COLOR_HUNT_MODE, GESTURE_MODE
    AUTONOMOUS_MODE = False
    FOLLOW_ME_MODE = False
    COLOR_HUNT_MODE = False
    GESTURE_MODE = False
    try:
        execute_tracked_movement(req.direction, req.duration)
        result = True
    except: result = False
    return {"status": "success", "result": result}

@app.post("/api/eyes")
def api_eyes(req: EyeColorRequest):
    hex_c = req.hex_color.lstrip('#')
    r, g, b = int(hex_c[0:2], 16), int(hex_c[2:4], 16), int(hex_c[4:6], 16)
    set_esp32_eyes(r, g, b)
    return {"status": "success", "rgb": [r, g, b]}

# NEW: reminders REST API (voice commands cover the common cases; this lets
# the dashboard or any other client list/add/delete reminders directly).
@app.get("/api/reminders")
async def api_get_reminders():
    with REMINDERS_LOCK:
        return {"status": "success", "reminders": list(REMINDERS)}

@app.post("/api/reminders")
async def api_add_reminder(req: ReminderRequest):
    if req.due_at_iso:
        try:
            due_dt = datetime.fromisoformat(req.due_at_iso)
        except Exception:
            return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid due_at_iso format, expected e.g. 2026-09-10T18:30:00"})
    elif req.due_in_minutes is not None:
        due_dt = datetime.now() + timedelta(minutes=req.due_in_minutes)
    else:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Provide either due_in_minutes or due_at_iso."})
    reminder = add_reminder(req.text, due_dt, recurring=req.recurring)
    return {"status": "success", "reminder": reminder}

@app.delete("/api/reminders/{reminder_id}")
async def api_delete_reminder(reminder_id: str):
    with REMINDERS_LOCK:
        before = len(REMINDERS)
        REMINDERS[:] = [r for r in REMINDERS if r["id"] != reminder_id]
        removed = len(REMINDERS) != before
        if removed:
            save_reminders_to_disk()
    return {"status": "success" if removed else "error"}

@app.post("/api/chat")
def api_chat(req: ChatRequest):
    global CURRENT_LANGUAGE
    CURRENT_LANGUAGE = req.language
    set_esp32_emotion("listening")
    ai_response = process_command_and_speech(req.message)
    return {"status": "success", "response": ai_response}

@app.post("/api/stt")
async def api_stt(audio: UploadFile = File(...)):
    set_esp32_emotion("listening")
    temp_audio = os.path.join(TEMP_AUDIO_DIR, f"temp_stt_{uuid.uuid4().hex}.webm")
    try:
        with open(temp_audio, "wb") as f: f.write(await audio.read())
        with open(temp_audio, "rb") as f:
            transcription = groq_client.audio.transcriptions.create(file=("audio.webm", f.read()), model="whisper-large-v3", language=CURRENT_LANGUAGE)
        return {"status": "success", "text": transcription.text}
    except: return {"status": "error", "text": ""}
    finally:
        if os.path.exists(temp_audio): os.remove(temp_audio)

@app.get("/api/ai-health")
async def api_ai_health(): return brain.diagnose()

@app.get("/api/vision-health")
async def api_vision_health():
    frame = vision_pipeline.get_latest_frame()
    return {
        "status": "success",
        "stream_status": "Online" if frame is not None else "Offline",
        "yolo_status": "Loaded" if vision_pipeline.yolo_model is not None else "Offline",
        "current_objects": vision_pipeline.get_detected_labels()
    }

if __name__ == "__main__":
    import uvicorn
    cleanup_stale_temp_audio()
    threading.Thread(target=register_server_with_esp32, daemon=True).start()
    threading.Thread(target=play_boot_sequence, daemon=True).start()
    threading.Thread(target=autonomous_navigation_loop, daemon=True).start()
    threading.Thread(target=follow_me_loop, daemon=True).start()
    threading.Thread(target=color_hunt_loop, daemon=True).start()
    threading.Thread(target=gesture_loop, daemon=True).start()
    threading.Thread(target=battery_monitor_loop, daemon=True).start()
    threading.Thread(target=reminder_loop, daemon=True).start()

    if LocalWakeWordListener:
        wake_listener = LocalWakeWordListener(callback_function=on_wake_word_detected)
        threading.Thread(target=wake_listener.start_listening, daemon=True).start()

    templates.env.auto_reload = True
    templates.env.cache = {}
    uvicorn.run(app, host="0.0.0.0", port=8000)
