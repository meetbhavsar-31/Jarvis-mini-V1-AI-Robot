import cv2
import re
import threading
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

from jarvis.common.logger import setup_logger
from jarvis.ai.vision import VisionPipeline
from jarvis.ai.brain import JarvisBrain
from jarvis.audio.tts import KokoroSpeaker
from jarvis.motion.motion_controller import MotionController

logger = setup_logger()
app = FastAPI(title="JARVIS MINI V2 - Web Tactical Dashboard")

# Initialize System Modules
logger.info("Initializing JARVIS Core Systems...")
vision_pipeline = VisionPipeline()
vision_pipeline.start_stream()

brain = JarvisBrain()
tts = KokoroSpeaker()
motion = MotionController()

# Pydantic Schemas
class MoveRequest(BaseModel):
    direction: str
    duration: float = 1.0

class ChatRequest(BaseModel):
    message: str

class EyeColorRequest(BaseModel):
    hex_color: str

# --------------------------------------------------------------------------
# VIDEO STREAM GENERATOR
# --------------------------------------------------------------------------
def generate_mjpeg_stream():
    """Generates continuous JPEG frames with YOLO annotations for browser streaming."""
    while True:
        frame = vision_pipeline.get_latest_frame()
        if frame is not None:
            resized_frame = cv2.resize(frame, (640, 480))
            ret, buffer = cv2.imencode('.jpg', resized_frame)
            if ret:
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.get("/video_feed")
def video_feed():
    return StreamingResponse(
        generate_mjpeg_stream(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

# --------------------------------------------------------------------------
# API ENDPOINTS
# --------------------------------------------------------------------------
@app.post("/api/move")
def api_move(req: MoveRequest):
    result = motion.execute_movement(req.direction, req.duration)
    return {"status": "success", "result": result}

@app.post("/api/eyes")
def api_eyes(req: EyeColorRequest):
    hex_c = req.hex_color.lstrip('#')
    r = int(hex_c[0:2], 16)
    g = int(hex_c[2:4], 16)
    b = int(hex_c[4:6], 16)
    result = motion.execute_eye_color(r, g, b)
    return {"status": "success", "rgb": [r, g, b], "result": result}

def process_voice_and_chat(user_message: str):
    """
    Processes motion triggers, LLM text generation, and speaks sentence-by-sentence.
    """
    try:
        user_intent = user_message.lower()

        # ==================================================================
        # 1. MOVEMENT INTENT DETECTION (Automated Motor Controls)
        # ==================================================================
        if "explore" in user_intent or "forward" in user_intent:
            logger.info("Chat Trigger: Executing forward movement...")
            threading.Thread(target=motion.execute_movement, args=("forward", 2.0)).start()
        elif "backward" in user_intent or "back" in user_intent:
            logger.info("Chat Trigger: Executing backward movement...")
            threading.Thread(target=motion.execute_movement, args=("backward", 2.0)).start()
        elif "left" in user_intent:
            logger.info("Chat Trigger: Turning left...")
            threading.Thread(target=motion.execute_movement, args=("left", 1.0)).start()
        elif "right" in user_intent:
            logger.info("Chat Trigger: Turning right...")
            threading.Thread(target=motion.execute_movement, args=("right", 1.0)).start()
        elif "stop" in user_intent:
            logger.info("Chat Trigger: Stopping motors...")
            threading.Thread(target=motion.execute_movement, args=("stop", 0.0)).start()

        # ==================================================================
        # 2. LLM THINKING & VOICE OUTPUT
        # ==================================================================
        response_text = brain.think(user_message)
        sentences = re.split(r'(?<=[.!?])\s+', response_text)
        for sentence in sentences:
            if sentence.strip():
                tts.speak(sentence.strip())

    except Exception as e:
        logger.error(f"Error processing AI voice and motion response: {e}")

@app.post("/api/chat")
def api_chat(req: ChatRequest):
    response_text = brain.think(req.message)
    threading.Thread(target=process_voice_and_chat, args=(req.message,)).start()
    return {"status": "success", "response": response_text}

# --------------------------------------------------------------------------
# WEB INTERFACE (HTML/CSS/JS DASHBOARD WITH MIC SUPPORT)
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>JARVIS MINI V2 - Web Dashboard</title>
        <style>
            body { background-color: #0d1117; color: #c9d1d9; font-family: 'Consolas', monospace; margin: 0; padding: 20px; }
            h1, h2 { color: #58a6ff; text-align: center; margin-bottom: 20px; }
            .container { display: flex; flex-wrap: wrap; gap: 20px; justify-content: center; }
            .panel { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 15px; width: 480px; }
            .video-container img { width: 100%; border-radius: 6px; border: 1px solid #30363d; }
            .btn-matrix { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; max-width: 240px; margin: 10px auto; }
            button { background: #21262d; color: #58a6ff; border: 1px solid #30363d; padding: 12px; font-weight: bold; font-size: 16px; border-radius: 6px; cursor: pointer; }
            button:hover { background: #30363d; color: #79c0ff; }
            .stop-btn { background: #8b0000; color: white; }
            .stop-btn:hover { background: #ff0000; }
            .mic-btn { background: #1f6feb; color: white; }
            .mic-btn.listening { background: #da3633; animation: pulse 1.5s infinite; }
            @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
            .color-picker { display: flex; justify-content: center; gap: 10px; margin-top: 10px; }
            .dot { width: 30px; height: 30px; border-radius: 50%; cursor: pointer; border: 2px solid white; }
            #chat-box { height: 180px; overflow-y: auto; background: #0d1117; border: 1px solid #30363d; padding: 10px; border-radius: 6px; margin-bottom: 10px; font-size: 13px; }
            .chat-input { display: flex; gap: 10px; }
            .chat-input input { flex: 1; padding: 10px; background: #0d1117; border: 1px solid #30363d; color: white; border-radius: 6px; }
        </style>
    </head>
    <body>
        <h1>JARVIS MINI V2 — TACTICAL WEB DASHBOARD</h1>
        <div class="container">
            
            <!-- VISION PANEL -->
            <div class="panel video-container">
                <h2>LIVE VISION STREAM</h2>
                <img src="/video_feed" alt="Live Stream">
            </div>

            <!-- CONTROL & CHAT PANEL -->
            <div class="panel">
                <h2>HARDWARE OVERRIDE</h2>
                <div class="btn-matrix">
                    <div></div>
                    <button onclick="sendMove('forward')">▲</button>
                    <div></div>
                    <button onclick="sendMove('left')">◄</button>
                    <button class="stop-btn" onclick="sendMove('stop')">■</button>
                    <button onclick="sendMove('right')">►</button>
                    <div></div>
                    <button onclick="sendMove('backward')">▼</button>
                    <div></div>
                </div>

                <h2 style="margin-top:20px;">ROBOT EYES COLOR</h2>
                <div class="color-picker">
                    <div class="dot" style="background:#00FFCC" onclick="changeEyeColor('#00FFCC')"></div>
                    <div class="dot" style="background:#FF3366" onclick="changeEyeColor('#FF3366')"></div>
                    <div class="dot" style="background:#00FF66" onclick="changeEyeColor('#00FF66')"></div>
                    <div class="dot" style="background:#FFCC00" onclick="changeEyeColor('#FFCC00')"></div>
                    <div class="dot" style="background:#3399FF" onclick="changeEyeColor('#3399FF')"></div>
                    <div class="dot" style="background:#CC33FF" onclick="changeEyeColor('#CC33FF')"></div>
                </div>

                <h2 style="margin-top:20px;">AI ASSISTANT TERMINAL</h2>
                <div id="chat-box">SYSTEM: Web tactical dashboard online.<br></div>
                <div class="chat-input">
                    <input type="text" id="userInput" placeholder="Ask JARVIS something..." onkeydown="if(event.key==='Enter') sendChat()">
                    <button id="micBtn" class="mic-btn" onclick="toggleSpeechRecognition()" title="Click to speak">🎤</button>
                    <button onclick="sendChat()">Send</button>
                </div>
            </div>

        </div>

        <script>
            let recognition = null;
            let isListening = false;

            if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
                const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                recognition = new SpeechRecognition();
                recognition.continuous = false;
                recognition.interimResults = false;
                recognition.lang = 'en-US';

                recognition.onresult = function(event) {
                    const speechToText = event.results[0][0].transcript;
                    document.getElementById('userInput').value = speechToText;
                    stopListeningAnimation();
                    sendChat(); // Automatically send when speech finishes
                };

                recognition.onerror = function(event) {
                    console.error('Speech recognition error', event.error);
                    stopListeningAnimation();
                };

                recognition.onend = function() {
                    stopListeningAnimation();
                };
            }

            function toggleSpeechRecognition() {
                if (!recognition) {
                    alert("Speech Recognition is not supported in this browser. Please use Google Chrome.");
                    return;
                }

                if (isListening) {
                    recognition.stop();
                } else {
                    recognition.start();
                    startListeningAnimation();
                }
            }

            function startListeningAnimation() {
                isListening = true;
                const btn = document.getElementById('micBtn');
                btn.classList.add('listening');
                btn.innerText = "⏹";
            }

            function stopListeningAnimation() {
                isListening = false;
                const btn = document.getElementById('micBtn');
                btn.classList.remove('listening');
                btn.innerText = "🎤";
            }

            function sendMove(dir) {
                fetch('/api/move', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({direction: dir, duration: 1.0})
                });
            }

            function changeEyeColor(hex) {
                fetch('/api/eyes', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({hex_color: hex})
                });
            }

            function sendChat() {
                const input = document.getElementById('userInput');
                const chatBox = document.getElementById('chat-box');
                const text = input.value.trim();
                if(!text) return;

                chatBox.innerHTML += `<b>You:</b> ${text}<br>`;
                input.value = '';
                chatBox.scrollTop = chatBox.scrollHeight;

                fetch('/api/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: text})
                })
                .then(res => res.json())
                .then(data => {
                    chatBox.innerHTML += `<b style="color:#58a6ff;">JARVIS:</b> ${data.response}<br><br>`;
                    chatBox.scrollTop = chatBox.scrollHeight;
                });
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)