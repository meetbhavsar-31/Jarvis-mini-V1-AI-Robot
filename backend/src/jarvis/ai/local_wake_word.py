import time
import speech_recognition as sr
from jarvis.common.logger import setup_logger

logger = setup_logger()

class LocalWakeWordListener:
    def __init__(self, callback_function):
        self.callback = callback_function
        self.running = False
        self.recognizer = sr.Recognizer()
        
        # Adjust sensitivity for background noise
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = True

    def start_listening(self):
        self.running = True
        # FIXED: Removed the microphone emoji to prevent Windows terminal crashes
        logger.info("[MIC] Local Offline Wake-Word Listener active. Listening for 'Jarvis'...")

        with sr.Microphone() as source:
            # Adjust for ambient noise briefly before starting loop
            self.recognizer.adjust_for_ambient_noise(source, duration=1.0)
            
            while self.running:
                try:
                    # Listen for audio input (non-blocking short chunks)
                    audio = self.recognizer.listen(source, timeout=1.0, phrase_time_limit=3.0)
                    
                    # Use PocketSphinx offline keyword recognition
                    text = self.recognizer.recognize_sphinx(audio, keyword_entries=[("jarvis", 1e-20)]).lower()
                    
                    if "jarvis" in text:
                        # FIXED: Removed the lightning bolt emoji
                        logger.info(f"[TRIGGER] Local Wake-word detected! Recognized text: {text}")
                        if self.callback:
                            self.callback()
                            
                except sr.WaitTimeoutError:
                    continue # Normal timeout, just loop back and listen again
                except Exception as e:
                    # Sphinx can throw errors if speech is unintelligible, safely ignore and continue
                    continue

    def stop_listening(self):
        self.running = False