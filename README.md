# JARVIS MINI V2 🤖🧠

> **An affordable, fully local, autonomous AI assistant and robot car.**

## 📖 What is JARVIS MINI?
JARVIS MINI bridges physical hardware with a powerful local desktop AI brain via Wi-Fi. By combining real-time computer vision, conversational speech processing, and edge hardware control, JARVIS can navigate physical spaces, recognize objects, and communicate naturally with users through an interactive web dashboard. 

**Privacy First:** All AI processing (Vision, LLM, Speech-to-Text, and Text-to-Speech) happens 100% locally on your machine. No cloud APIs are required!

---

## 🧠 Local AI Models Explained
Because AI models are massive files, they are **not** included in this repository to keep the download fast. You will need to download them locally before running the robot:

1. **The Brain (LLM):** Powered by Ollama. 
   * **Setup:** Install [Ollama](https://ollama.com/) and run `ollama run qwen2.5:3b` in your terminal to download the local conversation model.
2. **The Eyes (Vision):** Powered by YOLO (Ultralytics).
   * **Setup:** The Python script will automatically download the lightweight `yolov8n.pt` or `yolo11n.pt` model on its first run, or you can place them in the root directory.
3. **The Voice (TTS):** Powered by Kokoro ONNX.
   * **Setup:** Download `kokoro-v1.0.onnx` and `voices-v1.0.bin` and place them in the root directory.
4. **The Ears (STT):** Powered by Vosk.
   * **Setup:** Download the [Vosk English Model](https://alphacephei.com/vosk/models) (e.g., `vosk-model-small-en-us`) and extract it into the `resources/voices/` folder.

---

## 🛠️ Hardware Stack
* **Microcontrollers:** ESP8266 NodeMCU (Main Core) & ESP32-CAM (Vision Node)
* **Movement:** L298N Motor Driver, 2WD Smart Car Chassis
* **Sensors:** HC-SR04 Ultrasonic Sensor, PCF8574 I/O Expander
* **Face & Audio:** ST7789 TFT Display, INMP441 Microphone, MAX98357A Amplifier, 8Ω Speaker
* **Power:** 2x 18650 Battery Shield V8 Module (Recommended) OR Standard 5V USB Power Bank

---

## 🚀 Getting Started

### 1. Software Installation
```bash
# Clone the repository
git clone [https://github.com/meetbhavsar-31/Jarvis-mini-V1-AI-Robot.git](https://github.com/meetbhavsar-31/Jarvis-mini-V1-AI-Robot.git)
cd Jarvis-mini-V1-AI-Robot

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
