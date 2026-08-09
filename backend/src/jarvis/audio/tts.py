import os
import urllib.request
import threading
import sounddevice as sd
from kokoro_onnx import Kokoro
from jarvis.common.logger import setup_logger

logger = setup_logger()

class KokoroSpeaker:
    def __init__(self, voice="af_heart"): # Change "af_bella" to "af_heart" here
        logger.info("Initializing offline Kokoro TTS Engine...")
        self.voice = voice
        
        # 1. Define paths for the local AI models (Updated to v1.0)
        self.model_path = "kokoro-v1.0.onnx"
        self.voices_path = "voices-v1.0.bin"
        
        # 2. Download the models if this is the first time running
        self._ensure_models_downloaded()
        
        # 3. Initialize the ONNX Engine
        self.kokoro = Kokoro(self.model_path, self.voices_path)
        logger.info(f"Kokoro TTS Ready. Voice: {self.voice}")

    def _ensure_models_downloaded(self):
        """Automatically downloads the required ONNX model and voice profiles."""
        # Updated URLs for Kokoro v1.0 release
        model_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
        voices_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
        
        if not os.path.exists(self.model_path):
            logger.info("Downloading Kokoro v1.0 ONNX model... This will take a moment.")
            urllib.request.urlretrieve(model_url, self.model_path)
            logger.info("Model download complete!")
        
        if not os.path.exists(self.voices_path):
            logger.info("Downloading voice profiles...")
            urllib.request.urlretrieve(voices_url, self.voices_path)
            logger.info("Voice profiles download complete!")

    def _speak_thread(self, text: str):
        """The threaded function that generates and plays the audio offline."""
        logger.info(f"Synthesizing: '{text}'")
        try:
            # Generate the raw audio data
            audio, sample_rate = self.kokoro.create(
                text, voice=self.voice, speed=1.0, lang="en-us"
            )
            
            # Play the audio instantly using sounddevice
            sd.play(audio, sample_rate)
            sd.wait() # Wait for playback to finish
            
        except Exception as e:
            logger.error(f"Kokoro TTS Playback Error: {e}")

    def speak(self, text: str):
        """Spawns a new thread to synthesize and play text without blocking FastAPI."""
        speech_thread = threading.Thread(target=self._speak_thread, args=(text,))
        speech_thread.start()

# Standalone test
if __name__ == "__main__":
    speaker = KokoroSpeaker()
    speaker.speak("Hello! I am Jarvis, and my local neural voice is now fully operational.")
    
    # Keep the main thread alive long enough for the async speech to finish
    import time
    time.sleep(5)