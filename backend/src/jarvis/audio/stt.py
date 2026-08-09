import socket
import json
import os
import yaml
from vosk import Model, KaldiRecognizer, SetLogLevel
from jarvis.common.logger import setup_logger

logger = setup_logger()

class VoskListener:
    def __init__(self):
        SetLogLevel(-1) # Hide Vosk debug logs
        
        # Calculate root directory path (4 levels up from audio/)
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
        config_path = os.path.join(root_dir, "config", "audio.yaml")
        
        with open(config_path, 'r') as file:
            self.config = yaml.safe_load(file)['stt']
            
        model_path = os.path.join(root_dir, "resources", "voices", "vosk-stt-model")
        
        logger.info(f"Loading Vosk model from {model_path}...")
        try:
            self.model = Model(model_path)
            self.recognizer = KaldiRecognizer(self.model, self.config['sample_rate'])
            logger.info("Vosk STT Initialized.")
        except Exception as e:
            logger.error(f"Failed to load Vosk: {e}")
            raise
            
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", self.config['udp_rx_port']))
        self.sock.settimeout(1.0) # Prevent infinite blocking

    def listen(self):
        """Listens to the UDP socket and returns text when silence is detected."""
        logger.info(f"Listening for UDP audio on port {self.config['udp_rx_port']}...")
        while True:
            try:
                data, _ = self.sock.recvfrom(4096)
                if self.recognizer.AcceptWaveform(data):
                    result = json.loads(self.recognizer.Result())
                    text = result.get("text", "")
                    if text:
                        return text
            except socket.timeout:
                continue # Keep looping if no audio is received
            except Exception as e:
                logger.error(f"STT Error: {e}")
                return ""