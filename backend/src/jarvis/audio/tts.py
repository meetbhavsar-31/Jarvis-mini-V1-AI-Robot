import os
import uuid
import threading
import pygame
import requests
from dotenv import load_dotenv
from gtts import gTTS
from jarvis.common.logger import setup_logger

# Load environment variables from the .env file in your root folder
load_dotenv()

logger = setup_logger()

# Load ESP32 IP centrally from .env (e.g., http://192.168.1.50 or http://jarvis.local)
ESP32_IP = os.getenv("ESP32_IP", "http://jarvis.local").rstrip("/")

def send_mouth_animation_state(speaking: bool):
    """Sends a fast HTTP GET request to the ESP32 to trigger the mouth animation."""
    if not ESP32_IP:
        return

    def _request():
        state = "on" if speaking else "off"
        url = f"{ESP32_IP}/talk?state={state}"
        try:
            res = requests.get(url, timeout=0.8)
            logger.debug(f"Face Sync ({state}) -> {ESP32_IP}: {res.status_code}")
        except Exception as e:
            logger.debug(f"Failed to sync face animation: {e}")

    threading.Thread(target=_request, daemon=True).start()


class GoogleSpeaker:
    def __init__(self, lang="en", tld="co.uk"):
        logger.info("Initializing Hybrid TTS Engine (Google + Local Fallback + Auto Face Sync)...")
        self.lang = lang
        self.tld = tld
        self.speech_lock = threading.Lock()
        
        if not pygame.mixer.get_init():
            pygame.mixer.init()
            
        logger.info(f"Hybrid TTS Engine Ready (Lang: {self.lang}, Accent: {self.tld})")

    def _speak_thread(self, text: str):
        with self.speech_lock:
            filename = f"tts_{uuid.uuid4().hex}.mp3"
            success = False

            # 1. Trigger mouth animation ON
            send_mouth_animation_state(True)

            # --- ATTEMPT 1: GOOGLE CLOUD TTS (PRIMARY) ---
            try:
                logger.info(f"Synthesizing via Google TTS: '{text}'")
                tts = gTTS(text=text, lang=self.lang, tld=self.tld)
                tts.save(filename)
                
                pygame.mixer.music.load(filename)
                pygame.mixer.music.play()
                
                while pygame.mixer.music.get_busy():
                    pygame.time.Clock().tick(10)
                    
                success = True
            except Exception as google_error:
                logger.warning(f"Google TTS failed (offline): {google_error}. Switching to local SAPI fallback...")

            # --- ATTEMPT 2: STABLE LOCAL OFFLINE TTS (FALLBACK) ---
            if not success:
                try:
                    import pyttsx3
                    import pythoncom
                    
                    logger.info(f"Synthesizing via Local Fallback Engine: '{text}'")
                    pythoncom.CoInitialize()
                    
                    engine = pyttsx3.init()
                    engine.say(text)
                    engine.runAndWait()
                    
                    pythoncom.CoUninitialize()
                    success = True
                except Exception as local_error:
                    logger.error(f"Both Google and Local Fallback TTS failed: {local_error}")

            # 2. Turn mouth animation OFF
            send_mouth_animation_state(False)

            # Cleanup temporary file
            try:
                pygame.mixer.music.unload()
                if os.path.exists(filename):
                    os.remove(filename)
            except Exception:
                pass

    def speak(self, text: str):
        if not text or not text.strip():
            return
        speech_thread = threading.Thread(target=self._speak_thread, args=(text.strip(),), daemon=True)
        speech_thread.start()


if __name__ == "__main__":
    speaker = GoogleSpeaker()
    speaker.speak("Testing centralized ESP32 IP resolution and face sync.")