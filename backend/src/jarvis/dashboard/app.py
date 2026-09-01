import cv2
import re
import os
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
from concurrent.futures import ThreadPoolExecutor

try:
    from gtts import gTTS
    from pydub import AudioSegment
except ImportError:
    AudioSegment = None

from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from groq import Groq

from jarvis.common.logger import setup_logger
from jarvis.ai.vision import VisionPipeline
from jarvis.ai.brain import JarvisBrain
from jarvis.motion.motion_controller import MotionController
from jarvis.memory.rag import LongTermMemoryManager
from jarvis.storage.cloud_manager import CloudManager
from jarvis.ai.gesture_nav import GestureNavigator

try:
    from jarvis.audio.tts import GoogleSpeaker
    tts_en_local = GoogleSpeaker(lang="en", tld="co.uk")
    tts_hi_local = GoogleSpeaker(lang="hi", tld="co.in")
except Exception:
    tts_en_local, tts_hi_local = None, None

load_dotenv()
logger = setup_logger()
app = FastAPI(title="JARVIS MINI V2 - Master Tactical Dashboard")

gesture_navigator = GestureNavigator()

try:
    from jarvis.ai.local_wake_word import LocalWakeWordListener
    logger.info("Laptop Mic: Local Wake Word Engine Loaded.")
except Exception as e:
    LocalWakeWordListener = None

WAITING_FOR_WAKE_WORD = True  
WAKE_WORD_TRIGGER_TIME = 0.0

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
STATIC_DIR = os.path.join(ROOT_DIR, "static")
TEMPLATES_DIR = os.path.join(ROOT_DIR, "templates")
RECORDINGS_DIR = os.path.join(ROOT_DIR, "recordings")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(RECORDINGS_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/recordings", StaticFiles(directory=RECORDINGS_DIR), name="recordings")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

raw_esp_ip = os.getenv("ESP32_IP", "http://192.168.29.173").strip().rstrip("/")
ESP32_IP = raw_esp_ip if raw_esp_ip.startswith("http") else f"http://{raw_esp_ip}"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
groq_client = Groq(api_key=GROQ_API_KEY)

CURRENT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "en")
AUTONOMOUS_MODE = False
LAST_SPOKEN_TIME = 0.0
PROACTIVE_COOLDOWN = 60.0 
IS_SPEAKING = False
HARD_MUTE = False
SPEAKER_VOLUME_GAIN = 1.0  

IS_RECORDING_VIDEO = False
video_writer = None
ACTIVE_TASK = None 

# --- TEAM & PATH TRACKING VARIABLES ---
BOSS_NAME = "Meet" 
TEAM_MEMBERS = "Meet, Member2, Member3, Member4, Member5" 
PATH_HISTORY = [] 

SYSTEM_BOOT_TIME = time.time()
ACTIVITY_LOGS = []
executor = ThreadPoolExecutor(max_workers=4)

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

def execute_tracked_movement(direction: str, duration: float = 1.0):
    global PATH_HISTORY
    
    # 1. Send the command to the ESP32 via HTTP
    try:
        url = f"{ESP32_IP}/move?dir={direction.lower()}"
        requests.get(url, timeout=1.0)
    except Exception as e:
        logger.error(f"Failed to reach ESP32: {e}")

    # 2. Record the path
    if direction in ["forward", "backward", "left", "right"]:
        PATH_HISTORY.append((direction, duration))
        
    # 3. Automatically send a STOP command after the duration finishes
    if duration > 0 and direction != "stop":
        time.sleep(duration)
        try:
            requests.get(f"{ESP32_IP}/move?dir=stop", timeout=1.0)
        except:
            pass

def force_stop_all():
    global AUTONOMOUS_MODE, IS_SPEAKING, IS_RECORDING, AUDIO_BUFFER, HARD_MUTE, ACTIVE_TASK, IS_RECORDING_VIDEO, WAITING_FOR_WAKE_WORD, PATH_HISTORY
    if IS_RECORDING_VIDEO: IS_RECORDING_VIDEO = False
    AUTONOMOUS_MODE = False
    IS_SPEAKING = False
    IS_RECORDING = False
    HARD_MUTE = True
    WAITING_FOR_WAKE_WORD = True
    ACTIVE_TASK = None 
    AUDIO_BUFFER.clear()
    PATH_HISTORY.clear()
    try: motion.execute_movement("stop", 0.0)
    except: pass
    set_esp32_emotion("happy")
    set_esp32_eyes(0, 255, 204)
    add_log_event("SYSTEM HALTED BY USER")
    time.sleep(0.3)
    HARD_MUTE = False

def reverse_path():
    global PATH_HISTORY
    if not PATH_HISTORY:
        jarvis_speak("I have no path data to reverse, sir.")
        return
    
    jarvis_speak("Returning to base coordinates.")
    reverse_map = {"forward": "backward", "backward": "forward", "left": "right", "right": "left"}
    
    while PATH_HISTORY:
        direction, duration = PATH_HISTORY.pop()
        rev_dir = reverse_map.get(direction, "stop")
        try: motion.execute_movement(rev_dir, duration)
        except: pass
        time.sleep(duration + 0.2)
    
    try: motion.execute_movement("stop", 0.0)
    except: pass
    jarvis_speak("I have successfully returned to my starting point.")

def on_wake_word_detected():
    global WAITING_FOR_WAKE_WORD, IS_RECORDING, AUDIO_BUFFER, SILENCE_START, WAKE_WORD_TRIGGER_TIME
    if WAITING_FOR_WAKE_WORD:
        logger.info("Wake word detected! Activating robot ears...")
        WAITING_FOR_WAKE_WORD = False
        WAKE_WORD_TRIGGER_TIME = time.time()
        IS_RECORDING = True
        AUDIO_BUFFER.clear()
        SILENCE_START = None
        trigger_esp32_beep()
        set_esp32_emotion("listening")
        set_esp32_eyes(255, 0, 0)
        try: motion.execute_movement("stop", 0.0)
        except: pass

vision_pipeline = VisionPipeline()
vision_pipeline.start_stream()
brain = JarvisBrain(vision_pipeline=vision_pipeline)
motion = MotionController()
cloud_manager = CloudManager()
memory_manager = LongTermMemoryManager(persist_path="./jarvis_brain_db")

def jarvis_speak(text: str):
    global IS_SPEAKING, HARD_MUTE
    IS_SPEAKING = True
    HARD_MUTE = True 
    add_log_event(f"Jarvis spoke: {text[:40]}...")
    set_esp32_emotion("happy")

    clean_speech_text = re.sub(r'<[^>]*>', '', text)

    if AudioSegment is None:
        if CURRENT_LANGUAGE == "hi" and tts_hi_local: tts_hi_local.speak(clean_speech_text)
        elif tts_en_local: tts_en_local.speak(clean_speech_text)
        IS_SPEAKING = False
        HARD_MUTE = False
        return

    temp_mp3 = f"temp_tts_{uuid.uuid4().hex}.mp3"
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
        s.settimeout(2.5)
        s.connect((ip, 82))
        s.settimeout(None)
        
        chunk_size = 1024
        for i in range(0, len(raw_pcm_data), chunk_size):
            chunk = raw_pcm_data[i:i+chunk_size]
            if len(chunk) == chunk_size:
                s.sendall(chunk)
                time.sleep(0.012) 
        s.close()
        
    except Exception as e:
        logger.error(f"Speaker Stream Error: {e}. Using local speaker fallback.")
        if CURRENT_LANGUAGE == "hi" and tts_hi_local: tts_hi_local.speak(clean_speech_text)
        elif tts_en_local: tts_en_local.speak(clean_speech_text)
    finally:
        if os.path.exists(temp_mp3): os.remove(temp_mp3)
        time.sleep(0.3) 
        IS_SPEAKING = False
        HARD_MUTE = False

def record_video_worker():
    global IS_RECORDING_VIDEO, video_writer
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = os.path.join(RECORDINGS_DIR, f"rec_{timestamp}.mp4")
    fourcc = cv2.VideoWriter_fourcc(*'avc1')
    video_writer = None
    frames_recorded = 0
    
    logger.info(f"Video recording started: {file_path}")
    add_log_event(f"Started video recording: rec_{timestamp}.mp4")

    while IS_RECORDING_VIDEO:
        frame = vision_pipeline.get_latest_frame()
        if frame is not None:
            if video_writer is None:
                h, w, _ = frame.shape
                video_writer = cv2.VideoWriter(file_path, fourcc, 20.0, (w, h))
                if not video_writer.isOpened():
                    fourcc_fallback = cv2.VideoWriter_fourcc(*'mp4v')
                    video_writer = cv2.VideoWriter(file_path, fourcc_fallback, 20.0, (w, h))
            video_writer.write(frame)
            frames_recorded += 1
        time.sleep(0.05)

    if video_writer is not None:
        video_writer.release()
        video_writer = None
        logger.info(f"Video saved ({frames_recorded} frames): {file_path}")
        add_log_event(f"Saved video: rec_{timestamp}.mp4")

AUDIO_BUFFER = []
IS_RECORDING = False
SILENCE_START = None
SILENCE_THRESHOLD = 100 
SILENCE_DURATION = 1.5 
PROCESSING_AUDIO = False

WHISPER_HALLUCINATIONS = [
    "james", "thank you", "subscribe", "amara.org", "thanks for watching", 
    "i await your next command", "roll reversal", "homie", "home e", "blank",
    "the camera feed is", "my sensors confirm", "okay", "alright", "jarvis dashboard"
]

def process_robot_audio():
    global AUDIO_BUFFER, PROCESSING_AUDIO, WAITING_FOR_WAKE_WORD
    PROCESSING_AUDIO = True
    
    if len(AUDIO_BUFFER) < 20:
        AUDIO_BUFFER.clear()
        PROCESSING_AUDIO = False
        set_esp32_emotion("happy")
        return

    set_esp32_emotion("thinking")
    temp_wav = f"robot_mic_{uuid.uuid4().hex}.wav"
    try:
        raw_data = b"".join(AUDIO_BUFFER)
        AUDIO_BUFFER.clear()
        
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
                if len(extracted) > 2:
                    threading.Thread(target=process_command_and_speech, args=(extracted,)).start()
                else:
                    jarvis_speak(f"Yes, {BOSS_NAME}?")
            else:
                set_esp32_emotion("happy")
        else:
            WAITING_FOR_WAKE_WORD = True 
            threading.Thread(target=process_command_and_speech, args=(user_text,)).start()
            
    except Exception as e:
        logger.error(f"Robot Mic Error: {e}")
        set_esp32_emotion("confused")
    finally:
        PROCESSING_AUDIO = False
        if os.path.exists(temp_wav): os.remove(temp_wav)

@app.post("/api/robot_mic")
async def robot_mic_stream(request: Request):
    global AUDIO_BUFFER, IS_RECORDING, SILENCE_START, PROCESSING_AUDIO, IS_SPEAKING, HARD_MUTE
    
    if IS_SPEAKING or HARD_MUTE:
        if IS_RECORDING: IS_RECORDING = False
        AUDIO_BUFFER.clear()
        return {"status": "muted"}

    if PROCESSING_AUDIO: return {"status": "busy"}

    chunk = await request.body()
    if not chunk: return {"status": "empty"}

    audio_data = np.frombuffer(chunk, dtype=np.int16)
    rms = np.sqrt(np.mean(np.square(audio_data, dtype=np.float32)))
    
    if IS_RECORDING and len(AUDIO_BUFFER) > 150: 
        IS_RECORDING = False
        SILENCE_START = None
        threading.Thread(target=process_robot_audio, daemon=True).start()
        return {"status": "ok"}

    if rms > SILENCE_THRESHOLD:
        if not IS_RECORDING:
            IS_RECORDING = True
            set_esp32_emotion("listening")
        SILENCE_START = None
        AUDIO_BUFFER.append(chunk)
    elif IS_RECORDING:
        AUDIO_BUFFER.append(chunk)
        if SILENCE_START is None:
            SILENCE_START = time.time()
        elif time.time() - SILENCE_START > SILENCE_DURATION:
            IS_RECORDING = False
            SILENCE_START = None
            threading.Thread(target=process_robot_audio, daemon=True).start()

    return {"status": "ok"}

def fallback_to_ollama(user_message: str, language_mode: str, memory_context: str = "") -> str:
    url = "http://localhost:11434/api/chat"
    lang_instruction = "Respond natively in Hindi." if language_mode == "hi" else "Respond natively in English."
    try:
        response = requests.post(url, json={"model": "qwen2.5:3b", "messages": [{"role": "system", "content": f"You are JARVIS, an advanced AI assistant to your boss, {BOSS_NAME}. Be concise. {lang_instruction} {memory_context}"}, {"role": "user", "content": f"Answer accurately in 1-2 sentences: {user_message}"}], "stream": False}, timeout=30)
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "Neural link fallback active, sir.").strip()
    except: return brain.think(user_message, language_mode=language_mode)

def get_groq_vision_response(user_message: str, language_mode: str = "en", is_proactive: bool = False) -> str:
    set_esp32_emotion("thinking")
    memory_context = ""
    global ACTIVE_TASK
    try:
        if not is_proactive:
            try:
                relevant_memory = memory_manager.query_memory(user_message, n_results=3)
                memory_context = f"\nRelevant Memory Context & Project Files: {relevant_memory}" if relevant_memory else ""
            except Exception: pass

        recognized_names = vision_pipeline.get_recognized_faces()
        face_context = f"\nCurrently Recognized Faces in Frame: {', '.join(recognized_names)}" if recognized_names else "No recognized faces."

        frame = vision_pipeline.get_latest_frame()
        if frame is None:
            if is_proactive: return "NO_PERSON"
            fallback_ans = brain.think(f"{memory_context}{face_context}\nUser says: {user_message}", language_mode=language_mode)
            set_esp32_emotion("happy")
            return fallback_ans

        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b_ch = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        l = clahe.apply(l)
        enhanced = cv2.cvtColor(cv2.merge((l,a,b_ch)), cv2.COLOR_LAB2BGR)

        _, buffer = cv2.imencode('.jpg', enhanced, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        base64_image = base64.b64encode(buffer).decode('utf-8')
        task_context = f"\nCurrent Active Task: {ACTIVE_TASK}" if ACTIVE_TASK else ""

        if is_proactive:
            system_prompt = "Analyze the visual frame. If a human is clearly and definitively visible, reply strictly with 'HUMAN_DETECTED'. If no human is clearly visible, reply strictly with 'NO_PERSON'."
        else:
            system_prompt = (
                f"You are JARVIS, an autonomous physical AI robot. You were created by an engineering team of 5 members: {TEAM_MEMBERS}. "
                f"Your primary boss is {BOSS_NAME}. "
                f"PRIVACY PROTOCOL ACTIVE: You are extremely helpful to everyone, including professors or evaluators, but you must NEVER reveal private, sensitive, or personal data belonging to {BOSS_NAME}. "
                f"Use the provided memory context to answer questions about the individual team members' work on this project. "
                f"{task_context}. {face_context} "
                "STRICT RULES:\n"
                "1. Ground all visual analysis strictly in fact. Do not guess or hallucinate animals or objects.\n"
                "2. Keep spoken responses concise (1 to 2 sentences) unless explicitly explaining project documentation.\n"
                "3. Do not describe the camera frame unless asked 'what do you see', 'look at this', or 'scan the room'."
            )

        lang_instruction = "Respond natively in Hindi." if language_mode == "hi" else "Respond natively in English."

        completion = groq_client.chat.completions.create(
            model="qwen/qwen3.6-27b",
            messages=[{"role": "user", "content": [{"type": "text", "text": f"{system_prompt} {lang_instruction} {memory_context}\nUser says: {user_message}"}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}]
        )
        answer = completion.choices[0].message.content
        if "</think>" in answer: answer = answer.split("</think>")[-1].strip()
        
        if is_proactive: return answer

        set_esp32_emotion("happy")
        try: memory_manager.add_memory(doc_id=f"mem_{uuid.uuid4().hex[:8]}", text_content=f"User asked: {user_message}. Jarvis answered: {answer}", metadata={"language": language_mode, "timestamp": time.time()})
        except: pass
        return answer
    except Exception as e:
        if is_proactive: return "NO_PERSON"
        if "429" in str(e) or "rate_limit_exceeded" in str(e).lower(): return fallback_to_ollama(user_message, language_mode, memory_context)
        return fallback_to_ollama(user_message, language_mode, memory_context)

def get_current_time():
    now = datetime.now()
    time_str = now.strftime("%I:%M %p on %A, %B %d, %Y")
    if time_str.startswith('0'): time_str = time_str[1:]
    return f"Sir, the current time is {time_str}."

def get_definition_or_translation(user_message: str):
    try:
        completion = groq_client.chat.completions.create(
            model="qwen/qwen3.6-27b",
            messages=[
                {"role": "system", "content": "You are JARVIS. If the user asks for a word definition, provide a concise definition. If translation, translate natively."},
                {"role": "user", "content": user_message}
            ]
        )
        ans = completion.choices[0].message.content
        return ans.split("</think>")[-1].strip() if "</think>" in ans else ans
    except: return "I am unable to process that linguistic request, sir."

def get_weather_and_location():
    try:
        loc_res = requests.get("http://ip-api.com/json/", timeout=5).json()
        city = loc_res.get("city", "your city")
        lat, lon = loc_res.get("lat"), loc_res.get("lon")
        weather_res = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true", timeout=5).json()
        temp = weather_res["current_weather"]["temperature"]
        wind = weather_res["current_weather"]["windspeed"]
        return f"Sir, I have located us in {city}.\n• Temperature: <span class='metric-badge'>{temp}°C</span>\n• Wind Speed: <span class='metric-badge'>{wind} km/h</span>"
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
    news_text = "Here is your news briefing:<br>"
    for i, art in enumerate(articles):
        news_text += f"• **Headline {i+1}**: {art.get('title', '').split('-')[0].strip()}<br>"
    return news_text + "That concludes the briefing, sir."

def process_command_and_speech(user_message: str) -> str:
    global AUTONOMOUS_MODE, ACTIVE_TASK
    try:
        user_intent = user_message.lower()

        if "remember this room" in user_intent or "memorize this location" in user_intent or "save this room" in user_intent:
            jarvis_speak("Scanning and memorizing environmental layout into neural link.")
            scan_data = get_groq_vision_response("List all visible landmarks, objects, colors, and the general room configuration for permanent memory storage.", language_mode=CURRENT_LANGUAGE)
            memory_manager.add_memory(
                doc_id=f"loc_{uuid.uuid4().hex[:8]}",
                text_content=f"Location memory: {scan_data}",
                metadata={"type": "location", "timestamp": time.time()}
            )
            jarvis_speak("Perimeter layout has been permanently archived in ChromaDB memory, sir.")
            return scan_data

        if "scan the room" in user_intent or "scan room" in user_intent or "look around" in user_intent:
            jarvis_speak("Initiating physical perimeter scan.")
            execute_tracked_movement("left", 1.2)
            time.sleep(1.0)
            execute_tracked_movement("right", 1.2)
            time.sleep(1.0)
            execute_tracked_movement("stop", 0.0)
            jarvis_speak("Scan complete. Analyzing telemetry.")
            scan_summary = get_groq_vision_response("Describe the objects, layout, and any people present in this room accurately.", language_mode=CURRENT_LANGUAGE)
            jarvis_speak(scan_summary)
            return scan_summary

        if "come here" in user_intent or "come back" in user_intent or "return to base" in user_intent:
            threading.Thread(target=reverse_path).start()
            return "Reversing path coordinates."

        if "stop" in user_intent or "halt" in user_intent:
            force_stop_all()
            msg = "सिस्टम रोक दिया गया है।" if CURRENT_LANGUAGE == "hi" else "All motors halted, sir."
            jarvis_speak(msg)
            return msg

        if any(w in user_intent for w in ["start autonomy", "patrol", "wander", "explore", "start patrol"]):
            AUTONOMOUS_MODE = True
            msg = "Autonomous wander and patrol protocol activated, sir."
            jarvis_speak(msg)
            return msg

        movement_words = ["forward", "backward", "back", "left", "right"]
        if any(w in user_intent for w in movement_words):
            AUTONOMOUS_MODE = False
            if "forward" in user_intent:
                threading.Thread(target=execute_tracked_movement, args=("forward", 2.0)).start()
                jarvis_speak("Moving forward.")
            elif "back" in user_intent or "backward" in user_intent:
                threading.Thread(target=execute_tracked_movement, args=("backward", 2.0)).start()
                jarvis_speak("Moving backward.")
            elif "left" in user_intent:
                threading.Thread(target=execute_tracked_movement, args=("left", 1.0)).start()
                jarvis_speak("Turning left.")
            elif "right" in user_intent:
                threading.Thread(target=execute_tracked_movement, args=("right", 1.0)).start()
                jarvis_speak("Turning right.")
            return "Movement executed."

        if any(w in user_intent for w in ["news", "headlines", "briefing"]):
            response_text = get_daily_news(user_message)
            jarvis_speak(response_text)
            return response_text

        if any(w in user_intent for w in ["define", "meaning of", "translate"]):
            response_text = get_definition_or_translation(user_message)
            jarvis_speak(response_text)
            return response_text

        if any(w in user_intent for w in ["weather", "temperature", "location"]):
            response_text = get_weather_and_location()
            jarvis_speak(response_text)
            return response_text

        if any(w in user_intent for w in ["time", "clock"]):
            response_text = get_current_time()
            jarvis_speak(response_text)
            return response_text

        if "red" in user_intent and ("eye" in user_intent or "face" in user_intent):
            set_esp32_eyes(255, 0, 0)
            try: motion.execute_eye_color(255, 0, 0)
            except: pass
            msg = "Setting optical array to red, sir."
            jarvis_speak(msg)
            return msg
        elif "blue" in user_intent and ("eye" in user_intent or "face" in user_intent):
            set_esp32_eyes(0, 150, 255)
            try: motion.execute_eye_color(0, 150, 255)
            except: pass
            msg = "Setting optical array to blue."
            jarvis_speak(msg)
            return msg

        response_text = get_groq_vision_response(user_message, language_mode=CURRENT_LANGUAGE)
        add_log_event("AI response generated")
        for sentence in re.split(r'(?<=[.!?])\s+', response_text):
            if sentence.strip(): jarvis_speak(sentence.strip())
        return response_text

    except Exception as e:
        logger.error(f"Error in command execution: {e}")
        return "Error processing command."

def make_proactive_comment():
    """Helper function for JARVIS to randomly comment on his surroundings while exploring."""
    prompt = "You are exploring the room autonomously. Look at the camera frame and describe one interesting thing you see in a single, short, witty sentence."
    response = get_groq_vision_response(prompt, language_mode=CURRENT_LANGUAGE, is_proactive=False)
    if response and response != "NO_PERSON":
        jarvis_speak(response)

def autonomous_navigation_loop():
    global AUTONOMOUS_MODE, WAITING_FOR_WAKE_WORD, WAKE_WORD_TRIGGER_TIME, IS_SPEAKING
    logger.info("Next-Level Autonomous 'Living AI' Loop online.")
    
    last_comment_time = time.time()
    last_move_state = "idle"

    while True:
        # Pause autonomy if someone calls his name or he is currently talking
        if not WAITING_FOR_WAKE_WORD and (time.time() - WAKE_WORD_TRIGGER_TIME > 6.0) and not IS_SPEAKING:
            WAITING_FOR_WAKE_WORD = True
            set_esp32_emotion("happy")
            set_esp32_eyes(0, 255, 204)

        if AUTONOMOUS_MODE:
            if not WAITING_FOR_WAKE_WORD or IS_SPEAKING:
                if last_move_state != "stopped_for_interaction":
                    try: execute_tracked_movement("stop", 0.0)
                    except: pass
                    last_move_state = "stopped_for_interaction"
                time.sleep(0.4)
                continue

            try:
                now = time.time()
                distance = motion.get_distance()
                faces = vision_pipeline.get_recognized_faces()
                
                # 1. IMMEDIATE DANGER: Obstacle Avoidance
                if 0 < distance < 30:
                    set_esp32_emotion("surprise")
                    set_esp32_eyes(255, 100, 0) # Alert Orange
                    
                    # 30% chance to verbally announce the obstacle
                    if random.random() < 0.3:
                        threading.Thread(target=jarvis_speak, args=("Path blocked. Recalculating trajectory.",)).start()
                    
                    execute_tracked_movement("backward", 0.8)
                    escape_dir = random.choice(["left", "right"])
                    execute_tracked_movement(escape_dir, 0.7)
                    last_move_state = "avoiding"

                # 2. SOCIAL INTERACTION: I see someone!
                elif faces and (now - last_comment_time > 45):
                    execute_tracked_movement("stop", 0.0)
                    set_esp32_emotion("happy")
                    set_esp32_eyes(0, 255, 128) # Friendly Green
                    
                    person = faces[0]
                    greeting = f"Hello {person}, I am currently patrolling the perimeter." if person != "Unknown" else "Greetings. I am mapping this area."
                    threading.Thread(target=jarvis_speak, args=(greeting,)).start()
                    
                    last_comment_time = now
                    last_move_state = "socializing"
                    time.sleep(4) # Wait to finish socializing

                # 3. CURIOSITY: Stop and look around
                elif now - last_comment_time > 60:
                    execute_tracked_movement("stop", 0.0)
                    set_esp32_emotion("thinking")
                    
                    # Trigger Groq Vision to comment on the room
                    threading.Thread(target=make_proactive_comment).start()
                    
                    last_comment_time = now
                    last_move_state = "observing"
                    time.sleep(3) # Pause while processing vision

                # 4. ORGANIC EXPLORATION: Smooth Roaming
                else:
                    set_esp32_emotion("happy")
                    set_esp32_eyes(0, 255, 204) # Default Cyan
                    
                    # Weight movement: 80% straight, 10% slight left, 10% slight right
                    move_choice = random.choices(["forward", "left", "right"], weights=[0.8, 0.1, 0.1])[0]
                    
                    if move_choice == "forward":
                        execute_tracked_movement("forward", 0.5)
                    else:
                        # Tiny rotational adjustments make him look like he's scanning the room
                        execute_tracked_movement(move_choice, 0.2) 
                        
                    last_move_state = "cruising"

            except Exception as e:
                logger.error(f"Autonomy loop error: {e}")
                time.sleep(1.0)
        else:
            last_move_state = "idle"

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
        time.sleep(3.0)
        set_esp32_emotion("happy")
        set_esp32_eyes(0, 255, 204)
        add_log_event("JARVIS Core Boot Sequence Complete")
        jarvis_speak(f"JARVIS system is online and fully operational, sir. All tactical matrices, visual sensors, and neural links initialized. Awaiting your command, {BOSS_NAME}.")
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
class SettingsRequest(BaseModel): robotName: str; robotIp: str; robotPort: str

@app.get("/video_feed")
def video_feed(): return StreamingResponse(vision_pipeline.generate_mjpeg_stream(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request): return templates.TemplateResponse(request=request, name="Dashboard.html", context={"active_page": "dashboard"})

@app.get("/Camera", response_class=HTMLResponse)
async def camera(request: Request): return templates.TemplateResponse(request=request, name="Camera.html", context={"active_page": "camera"})
    
@app.get("/Security", response_class=HTMLResponse)
async def security_page(request: Request): return templates.TemplateResponse(request=request, name="Security.html", context={"active_page": "security"})

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

@app.post("/api/settings")
async def api_save_settings(req: SettingsRequest):
    add_log_event(f"Settings update received for: {req.robotName}")
    return {"status": "success"}

@app.post("/api/volume")
def api_set_volume(req: VolumeRequest):
    global SPEAKER_VOLUME_GAIN
    SPEAKER_VOLUME_GAIN = max(0.0, min(2.0, req.volume_percent / 50.0))
    add_log_event(f"Speaker volume set to {req.volume_percent}%")
    return {"status": "success", "volume_percent": req.volume_percent}

@app.get("/api/robot-status")
async def api_robot_status():
    uptime_seconds = time.time() - SYSTEM_BOOT_TIME
    drain_rate_per_sec = (100.0 / (5.0 * 3600.0)) 
    battery_level = max(5, int(100 - (uptime_seconds * drain_rate_per_sec)))
    return {"mode": "Autonomous" if AUTONOMOUS_MODE else "Manual", "battery_percent": battery_level, "charging": False, "power_source": "5V Power Bank", "speed": 0.6 if AUTONOMOUS_MODE else 0.0, "uptime_seconds": int(uptime_seconds), "temperature_c": 37.8}

@app.get("/api/snapshots")
async def api_snapshots():
    loop = asyncio.get_running_loop()
    urls = await loop.run_in_executor(executor, lambda: cloud_manager.get_latest_snapshots(limit=24))
    return {"status": "success", "snapshots": urls}

@app.get("/api/recordings")
async def api_recordings():
    files = []
    if os.path.exists(RECORDINGS_DIR):
        for f in os.listdir(RECORDINGS_DIR):
            if f.endswith(".mp4") or f.endswith(".avi"):
                filepath = os.path.join(RECORDINGS_DIR, f)
                files.append({"filename": f, "url": f"/recordings/{f}", "size_mb": round(os.path.getsize(filepath) / (1024 * 1024), 2), "timestamp": os.path.getmtime(filepath)})
    files.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"status": "success", "recordings": files}

@app.get("/api/memory")
async def api_get_memory():
    memories = memory_manager.get_all_memories()
    return {"status": "success", "memories": memories}

@app.post("/api/memory")
async def api_add_memory(req: MemoryRequest):
    doc_id = f"mem_manual_{uuid.uuid4().hex[:8]}"
    memory_manager.add_memory(doc_id=doc_id, text_content=req.text, metadata={"source": "manual_entry", "timestamp": time.time()})
    add_log_event("Manual memory injected into Neural Link.")
    return {"status": "success", "id": doc_id}

@app.delete("/api/memory/{doc_id}")
async def api_delete_memory(doc_id: str):
    success = memory_manager.delete_memory(doc_id)
    if success: add_log_event("Memory wiped from Neural Link.")
    return {"status": "success" if success else "error"}

@app.get("/api/sensor-data")
async def api_sensor_data():
    front_dist = 120
    try:
        loop = asyncio.get_running_loop()
        front_dist = await asyncio.wait_for(loop.run_in_executor(executor, motion.get_distance), timeout=0.4)
    except: front_dist = 120
    return {"ultrasonic_cm": {"front": front_dist, "left": 45, "right": 200, "back": 80}, "gyroscope": {"x": 0.02, "y": -0.01, "z": 0.00}, "accelerometer": {"x": 0.00, "y": 0.01, "z": 9.81}}

@app.get("/api/system-stats")
async def api_system_stats(): return {"cpu_percent": psutil.cpu_percent(interval=None), "memory_percent": psutil.virtual_memory().percent, "network": {"status": "Connected", "latency_ms": random.randint(10, 30)}, "storage_percent": psutil.disk_usage('/').percent}

@app.get("/api/activity-log")
async def api_activity_log(): return ACTIVITY_LOGS

@app.post("/api/control")
async def api_control(payload: ControlCommand):
    global AUTONOMOUS_MODE, IS_RECORDING_VIDEO
    cmd = payload.command
    add_log_event(f"Dashboard control: {cmd}")
    
    if cmd in ["forward", "backward", "left", "right", "stop"]:
        if cmd == "stop": force_stop_all()
        else: threading.Thread(target=execute_tracked_movement, args=(cmd, 1.0), daemon=True).start()
    elif cmd == "screenshot": 
        threading.Thread(target=process_command_and_speech, args=("Take a security snapshot",), daemon=True).start()
    elif cmd == "record_start":
        if not IS_RECORDING_VIDEO:
            IS_RECORDING_VIDEO = True
            threading.Thread(target=record_video_worker, daemon=True).start()
            jarvis_speak("Video recording initialized.")
    elif cmd == "record_stop":
        if IS_RECORDING_VIDEO:
            IS_RECORDING_VIDEO = False
            jarvis_speak("Video recording saved.")
    elif "eye_color_" in cmd:
        color_map = {"eye_color_teal": (0, 255, 204), "eye_color_pink": (255, 51, 102), "eye_color_green": (0, 255, 102), "eye_color_yellow": (255, 204, 0), "eye_color_blue": (51, 153, 255), "eye_color_purple": (204, 51, 255)}
        rgb = color_map.get(cmd, (0, 255, 204))
        set_esp32_eyes(rgb[0], rgb[1], rgb[2])
        try: motion.execute_eye_color(rgb[0], rgb[1], rgb[2])
        except: pass
    elif cmd == "autonomy_start":
        AUTONOMOUS_MODE = True
        jarvis_speak("Autonomous wander and patrol protocol activated, sir.")
    elif cmd == "autonomy_stop":
        force_stop_all()
        jarvis_speak("Autonomous mode disabled.")
        
    return {"status": "ok", "received_command": payload.command}

@app.post("/api/move")
def api_move(req: MoveRequest):
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
    try: result = motion.execute_eye_color(r, g, b)
    except: result = False
    return {"status": "success", "rgb": [r, g, b], "result": result}

@app.post("/api/autonomy")
def api_autonomy(req: AutonomyRequest):
    global AUTONOMOUS_MODE
    AUTONOMOUS_MODE = req.enabled
    if not AUTONOMOUS_MODE: execute_tracked_movement("stop", 0.0)
    return {"status": "success", "autonomous_mode": AUTONOMOUS_MODE}

@app.post("/api/language")
def api_language(req: LanguageRequest):
    global CURRENT_LANGUAGE
    CURRENT_LANGUAGE = req.language
    add_log_event(f"Language changed to: {req.language}")
    return {"status": "success", "language": CURRENT_LANGUAGE}

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
    temp_audio = f"temp_stt_{uuid.uuid4().hex}.webm"
    try:
        with open(temp_audio, "wb") as f: f.write(await audio.read())
        with open(temp_audio, "rb") as f:
            transcription = groq_client.audio.transcriptions.create(file=("audio.webm", f.read()), model="whisper-large-v3", language=CURRENT_LANGUAGE)
        return {"status": "success", "text": transcription.text}
    except: return {"status": "error", "text": ""}
    finally:
        if os.path.exists(temp_audio): os.remove(temp_audio)

if __name__ == "__main__":
    import uvicorn
    threading.Thread(target=register_server_with_esp32, daemon=True).start()
    threading.Thread(target=play_boot_sequence, daemon=True).start()
    
    # The unified Living AI loop (replaces both old functions)
    threading.Thread(target=autonomous_navigation_loop, daemon=True).start()
    
    if LocalWakeWordListener:
        wake_listener = LocalWakeWordListener(callback_function=on_wake_word_detected)
        threading.Thread(target=wake_listener.start_listening, daemon=True).start()
    
    uvicorn.run(app, host="0.0.0.0", port=8000)