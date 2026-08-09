# JARVIS MINI V2 🤖🧠

> **An affordable, autonomous AI assistant and robot car bridging physical microcontroller hardware with a powerful local AI brain.**

## 📖 Introduction
JARVIS MINI is an advanced, low-cost autonomous AI assistant and robot car. It bridges physical microcontroller hardware with a powerful local desktop AI brain via Wi-Fi. By combining real-time computer vision (YOLO), conversational speech processing (Browser Web Speech API & Kokoro TTS), and edge hardware control (ESP32 NodeMCU/ESP8266 and ESP32-CAM), JARVIS can navigate physical spaces, recognize objects, and communicate naturally with users through an interactive web-based FastAPI dashboard.

## ✨ Features
- **Conversational AI:** Local voice processing utilizing Qwen 2.5 (Ollama) or Gemini models.
- **Computer Vision:** Real-time object detection and context injection via ESP32-CAM and YOLO.
- **Autonomous Movement:** DC motor control and obstacle avoidance (HC-SR04) via L298N and PCF8574 I/O Expander.
- **Interactive Face:** ST7789 TFT display for dynamic visual feedback and status monitoring.
- **Local Telemetry & Memory:** SQLite database integration for logging chat history and vision state.
- **Dual Power Options:** Supports both standard USB Power Banks and upgraded 2x 18650 Battery Shield V8 modules.

## 🛠️ Hardware Stack
- **Microcontrollers:** ESP8266 NodeMCU & ESP32-CAM (OV2640)
- **Motor Control:** L298N Motor Driver, 2WD Smart Car Chassis
- **Sensors & Expansion:** HC-SR04 Ultrasonic Sensor, PCF8574 I/O Expander
- **Display & Audio:** ST7789 TFT Display, INMP441 Mic, MAX98357A Amplifier, 8Ω Speaker
- **Power:** 2x 18650 Battery Shield V8 Module (or USB Power Bank)

## 💻 Software Stack
- **Backend:** Python 3.10+, FastAPI, SQLite
- **AI & Vision:** Ultralytics YOLOv8, Ollama (Qwen2.5:3b), Kokoro ONNX TTS
- **Firmware:** Arduino IDE, C/C++ 

## 🚀 Getting Started

### 1. Hardware Setup
Follow the complete system wiring guide to construct the physical robot. Main phases include:
1. Power Distribution Setup (+5V/GND Rails)
2. Control & Expansion Core (PCF8574)
3. Movement Subsystem (L298N)
4. Obstacle Detection (HC-SR04)
5. Robot Face Display (ST7789)
6. Audio Subsystem (MAX98357A)

### 2. Software Installation
```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/JARVIS_MINI_V2.git
cd JARVIS_MINI_V2

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`

# Install dependencies
pip install -r requirements.txt
```

### 3. Running the System
1. Flash the `.ino` firmware to your ESP8266 and ESP32-CAM.
2. Start the local LLM server (e.g., `ollama run qwen2.5:3b`).
3. Launch the FastAPI backend:
   ```bash
   python -m uvicorn src.main:app --reload
   ```
4. Access the web dashboard at `http://localhost:8000`.
