import os
import uuid
import asyncio
import threading
import pygame
import edge_tts
from jarvis.common.logger import setup_logger

logger = setup_logger()

class EdgeSpeaker:
    def __init__(self, voice="en-US-JennyNeural"):
        logger.info("Initializing Edge TTS Engine...")
        self.voice = voice
        # Initialize pygame mixer for audio playback
        pygame.mixer.init()
        logger.info(f"Edge TTS Engine Ready. Voice: {self.voice}")

    async def _generate_audio_async(self, text: str, filename: str):
        """Asynchronously generates the MP3 file using Edge TTS."""
        communicate = edge_tts.Communicate(text=text, voice=self.voice)
        await communicate.save(filename)

    def _speak_thread(self, text: str):
        """The threaded function that generates and plays the audio."""
        logger.info(f"Synthesizing: '{text}'")
        
        # Create a unique filename to prevent overwriting if Jarvis speaks rapidly
        filename = f"tts_{uuid.uuid4().hex}.mp3"

        try:
            # 1. Generate the MP3
            asyncio.run(self._generate_audio_async(text, filename))
            
            # 2. Play the MP3 using Pygame
            pygame.mixer.music.load(filename)
            pygame.mixer.music.play()
            
            # 3. Wait for playback to finish
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
                
        except Exception as e:
            logger.error(f"Edge TTS Playback Error: {e}")
        finally:
            # 4. Clean up: Stop the mixer and delete the temporary file
            # We must unload the music in Pygame before deleting the file
            pygame.mixer.music.unload() 
            if os.path.exists(filename):
                os.remove(filename)

    def speak(self, text: str):
        """Spawns a new thread to synthesize and play text without blocking."""
        speech_thread = threading.Thread(target=self._speak_thread, args=(text,))
        speech_thread.start()

# Standalone test
if __name__ == "__main__":
    speaker = EdgeSpeaker()
    speaker.speak("Hello! I am Jarvis, and I am now speaking using Microsoft Edge Neural TTS.")