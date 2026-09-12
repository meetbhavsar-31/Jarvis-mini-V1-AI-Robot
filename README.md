# 🤖 JARVIS MINI V1 — Master Tactical AI Robot

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-Computer%20Vision-5C3EE8?style=for-the-badge&logo=opencv&logoColor=white)
![ESP32](https://img.shields.io/badge/ESP32-Hardware%20Bridge-E7352C?style=for-the-badge&logo=espressif&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-VLM%20%26%20Whisper-F55036?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

<p align="center">
  <b>An autonomous, multi-modal robotics companion: it sees, hears, speaks, moves, remembers, patrols, and alerts you on your phone — combining an ESP32 hardware bridge with a FastAPI brain backed by cloud and local AI.</b>
</p>

</div>

---

## 📑 Table of Contents
- [Project Overview](#-project-overview)
- [System Architecture](#-system-architecture)
- [Key Features](#-key-features)
- [Hardware & Pins](#-hardware--pins)
- [Directory Structure](#-directory-structure)
- [Installation & Setup](#-installation--setup)
- [Environment Configuration](#-environment-configuration)
- [Running the System](#-running-the-system)
- [API Reference](#-api-reference)
- [Voice Commands](#-voice-commands)
- [Autonomous Behaviors & Protocols](#-autonomous-behaviors--protocols)
- [Known Limitations](#-known-limitations)
- [Troubleshooting](#-troubleshooting)

---

## 🌟 Project Overview

**JARVIS MINI V1** is a modular robotics platform that bridges embedded hardware (ESP32 / ESP32-CAM) with cloud and local AI. The central server is written in **FastAPI** and provides:

- **Live MJPEG camera streaming** and a web dashboard for full manual/voice/autonomous control.
- **Natural language interaction** in English and Hindi, powered by Groq (primary), Gemini (vision fallback), and Ollama (local offline fallback).
- **Object/person tracking and gesture navigation** via YOLO11n and MediaPipe.
- **Long-term memory** (ChromaDB) for recall and proactive fact extraction across conversations.
- **Autonomous patrol with intruder/acoustic sentry**, path recording, and reverse-to-base.
- **Real push notifications** (Telegram / ntfy.sh — both free) for security events, low battery, and voice-triggered emergencies.
- **Voice-driven reminders** with natural-language time parsing, persisted across restarts.

One motive ties it all together: give a person real-time awareness of, and hands-free control over, their own space — even when they're not looking at it. Events don't just get logged somewhere you'd have to go check; they get pushed to your phone.

---

## 🏗 System Architecture

```text
       ┌────────────────────────────────────────────────────────┐
       │                 JARVIS Brain (FastAPI)                 │
       │                                                        │
       │  ┌─────────────────┐  ┌─────────────────────────────┐  │
       │  │  Vision Pipeline│  │  Groq LLM / Whisper STT     │  │
       │  │ (YOLO/Gesture)  │  │  + Gemini + Ollama Fallback │  │
       │  └────────┬────────┘  └──────────────┬──────────────┘  │
       │           │                          │                 │
       │  ┌────────┴────────┐  ┌──────────────┴──────────────┐  │
       │  │ ChromaDB Memory │  │ gTTS / Socket Audio Stream  │  │
       │  └─────────────────┘  └─────────────────────────────┘  │
       │  ┌─────────────────┐  ┌─────────────────────────────┐  │
       │  │Reminders (JSON) │  │ Alerts (Telegram / ntfy)    │  │
       │  └─────────────────┘  └─────────────────────────────┘  │
       └───────────────────────────┬────────────────────────────┘
                                    │
                   HTTP REST / TCP Raw Audio / MJPEG
                                    │
         ┌──────────────────────────┴─────────────────────────┐
         │                                                     │
         ▼                                                     ▼
┌──────────────────┐                                 ┌──────────────────┐
│   ESP32-S Node    │                                 │    ESP32-CAM     │
│  (Locomotion,      │                                │  (Headless Vision│
│  Sensors, Eyes,     │                               │    Capture Node) │
│    Audio I/O)        │                              └──────────────────┘
└──────────────────┘
```

**Two separate ESP32 boards, two separate IPs.** This trips people up constantly: `ESP32_IP` (motors/eyes/speaker) and `ESP32_CAM_STREAM_URL` (camera) are different devices on your network. Both are editable live from the dashboard's Settings page.

---

## ✨ Key Features

### Perception
- YOLO11n object and person detection with single-flight inference (no overlapping/out-of-order detection threads) and staleness filtering (won't act on a detection older than ~3.5s)
- Color-based object detection (HSV segmentation: red/green/blue/yellow)
- Hand-gesture control via MediaPipe (open palm = stop, 1–2 fingers = forward, thumb-direction = turn)
- Gemini-powered hazard/path scanning
- Ultrasonic distance sensing

### Mobility
- Manual drive (dashboard D-pad / WASD)
- Autonomous patrol with obstacle avoidance
- Follow-me — tracks a person **or any named object** ("follow the chair")
- "Go to the [object]" — drives to and stops at a target, not just describes it
- Path history + "come back" reverse-to-start

### Intelligence
- Multi-engine reasoning with automatic fallback: Groq → Gemini → Ollama
- Selectable engine preference (cloud-first or local-first) from the Settings page
- Tool-calling: live web search (Tavily), system diagnostics, sensor queries
- Long-term semantic memory (ChromaDB) with proactive fact extraction
- Bilingual (English/Hindi) command parsing

### Safety & Alerting
- Intruder sentry: patrol halt + snapshot + **real push notification**
- Acoustic anomaly detection (loud-noise triggered scan + alert)
- Low-battery voice + push alert
- Manual/voice emergency trigger ("Jarvis, I need help")
- All alert dispatch is free — Telegram Bot API and/or ntfy.sh, no paid tier required

### Task Management
- Voice-set reminders: `"remind me to take medicine in 20 minutes"`, `"...after 5 minutes"`, `"...at 6pm"`
- Reminders persist across restarts, fire via speech + push notification
- List/cancel by voice; full CRUD via REST API

### Interface
- Live web dashboard: camera feed, chat, manual controls, mode toggles, activity log, snapshot gallery
- Settings page with **live-editable** robot IP, camera IP, AI engine, wake-word toggle — no restart required
- Time-aware morning briefing (weather + news + memory recap)

---

## 🔌 Hardware & Pins

Two ESP32 boards:

**ESP32-S (motion/eyes/speaker/mic)** — see `firmware/esp32-dev/jarvis_firmware.ino`

| Function | Pin(s) |
|---|---|
| I2C (PCF8574 motor expander) | SDA=21, SCL=22 |
| Motor driver (via PCF8574 P0–P3) | IN1=0, IN2=1, IN3=2, IN4=3 |
| ST7735 LCD (face display) | CS=5, RST=4, DC=19 (VSPI: MOSI=23, SCLK=18) |
| Ultrasonic (HC-SR04) | TRIG=13, ECHO=33 |

**ESP32-CAM (vision node)** — see `firmware/esp32_cam/camera_web_server.ino`, runs the MJPEG stream consumed by `vision.py`.

---

## 📁 Directory Structure

```text
.
├── backend/
│   └── src/jarvis/
│       ├── dashboard/
│       │   └── app.py              # FastAPI server, routes, background loops (the core)
│       ├── ai/
│       │   ├── vision.py           # YOLO detection, MJPEG consumption, color tracking
│       │   ├── brain.py            # LLM reasoning, tool-calling, engine fallback
│       │   ├── gesture_nav.py      # MediaPipe hand-gesture recognition
│       │   ├── autonomy.py         # standalone tracker module -- currently UNUSED,
│       │   │                       #   not imported anywhere (see Known Limitations)
│       │   ├── local_wake_word.py  # offline "Jarvis" wake-word listener
│       │   └── mcp_server.py       # (legacy/parallel, not covered by this fix pass)
│       ├── motion/
│       │   └── motion_controller.py  # ESP32 movement/distance HTTP client
│       ├── alerts/
│       │   └── notifier.py         # Telegram + ntfy.sh push notification dispatch
│       ├── memory/                 # ChromaDB RAG + local SQLite chat history
│       ├── storage/
│       │   └── cloud_manager.py    # Cloudinary snapshot upload/gallery
│       ├── audio/                  # TTS/STT helpers (legacy/parallel, not covered)
│       └── common/logger.py
├── templates/                      # Jinja2 dashboard pages
├── static/                         # dashboard CSS/JS
├── firmware/
│   ├── esp32-dev/jarvis_firmware.ino    # motion/eyes/speaker board
│   └── esp32_cam/camera_web_server.ino  # camera board
├── .env.example
├── requirements.txt
└── README.md
```

**Scope note:** this fix pass covered `dashboard/app.py`, `ai/vision.py`, `ai/brain.py`, `ai/gesture_nav.py`, `ai/autonomy.py`, `motion/motion_controller.py`, the new `alerts/notifier.py`, and `templates/Settings.html`. `dashboard/desktop_app.py`, `audio/stt.py`, `audio/tts.py`, `ai/mcp_server.py`, `memory/*`, and `robot_runtime/*` exist in this repo but were **not** reviewed or modified — treat them as unverified legacy code until someone goes through them the same way.

---

## 🛠 Installation & Setup

```powershell
# 1. Clone
git clone https://github.com/meetbhavsar-31/Jarvis-mini-V1-AI-Robot.git
cd Jarvis-mini-V1-AI-Robot

# 2. Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
copy .env.example .env
# then edit .env with your real API keys and robot IPs

# 5. Flash the two ESP32 boards
# See firmware/esp32-dev/jarvis_firmware.ino and firmware/esp32_cam/camera_web_server.ino
```

If you're using the local Ollama fallback engine, also install and start [Ollama](https://ollama.com) and pull the model set in `OLLAMA_LOCAL_MODEL`.

---

## ⚙️ Environment Configuration

See `.env.example` for the full annotated list. Summary:

| Variable | Required | Purpose |
|---|---|---|
| `ESP32_IP` | Yes | Motion/eyes/speaker board address |
| `ESP32_CAM_STREAM_URL` | Yes | Camera board MJPEG stream URL |
| `GROQ_API_KEY` | Yes | Primary reasoning + Whisper STT |
| `GEMINI_API_KEY` | Recommended | Vision fallback, hazard scan |
| `OLLAMA_LOCAL_MODEL` | For local engine | Offline fallback model name |
| `TAVILY_API_KEY` | Optional | Live web search tool |
| `CLOUDINARY_URL` | Optional | Security snapshot storage |
| `NEWS_API_KEY` | Optional | Morning briefing headlines |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Optional | Free push alerts |
| `NTFY_TOPIC` / `NTFY_SERVER` | Optional | Free push alerts (no signup) |
| `API_AUTH_TOKEN` | Optional | Protects state-changing dashboard routes |

`ESP32_IP` and `ESP32_CAM_STREAM_URL` can also be changed **live** from the Settings page — useful since these IPs commonly drift after a router/DHCP renewal, and editing `.env` requires a restart.

> ⚠️ Never commit a real `.env` — only `.env.example` with placeholders belongs in git. This repo previously had real API keys committed directly into `.env.example`; if you inherited a clone from before this fix, rotate any keys you find in git history immediately.

---

## ▶️ Running the System

```powershell
$env:PYTHONPATH="backend/src"
$env:PYTHONIOENCODING="utf-8"
python -m jarvis.dashboard.app
```

Then open `http://<your-laptop-ip>:8000` in a browser. On first boot, the two ESP32 boards should already be powered on and connected to the same WiFi network so the server can register itself and the video stream can connect.

---

## 📡 API Reference

All routes are on the FastAPI server (default port 8000). Routes marked 🔒 require `X-API-Token` header if `API_AUTH_TOKEN` is set.

| Method | Route | Purpose |
|---|---|---|
| GET | `/` | Dashboard |
| GET | `/video_feed` | MJPEG camera stream |
| POST | `/api/chat` | Send a text/voice command |
| POST | `/api/stt` | Upload audio for transcription |
| GET/POST | `/api/move` 🔒 | Manual movement |
| POST | `/api/control` 🔒 | Dashboard action buttons (autonomy, screenshot, stop) |
| POST | `/api/eyes` | Set eye color |
| POST | `/api/volume` | Set speaker volume |
| GET | `/api/robot-status` | Mode, battery, online status |
| GET | `/api/sensor-data` | Ultrasonic distance |
| GET | `/api/activity-log` | Recent event log |
| GET | `/api/snapshots` | Cloud snapshot gallery |
| DELETE | `/api/snapshots/{id}` 🔒 | Delete a snapshot |
| GET/POST | `/api/memory` | View/add long-term memory |
| DELETE | `/api/memory/{id}` 🔒 | Delete a memory |
| GET/POST | `/api/reminders` | List/add reminders |
| DELETE | `/api/reminders/{id}` | Delete a reminder |
| GET/POST | `/api/settings` | Live robot config (IP, engine, wake word, etc.) |
| POST | `/api/language` | Set active language |
| GET | `/api/ai-health` / `/api/vision-health` | Diagnostics |

---

## 🗣 Voice Commands

Movement, follow/track, go-to-object, color hunt, gestures, patrol, reminders, alerts, and briefings — in English and Hindi. See the full command table in the project's user guide, or `process_command_and_speech()` in `app.py` for the authoritative list.

---

## 🤖 Autonomous Behaviors & Protocols

- **Patrol loop**: wanders, avoids obstacles, halts + alerts on person detection (30s cooldown between alerts), makes proactive observations every ~60s using vision + memory context.
- **Follow-me loop**: closed-loop tracking of a person or named object, maintains a "personal space" distance band, backs off if too close.
- **Color-hunt loop**: HSV-based homing on a target color, stops on arrival.
- **Gesture loop**: hold-until-changed movement (not pulsed), matching the dashboard D-pad's behavior for reliability over lossy WiFi links.
- **Reminder loop**: polls every 15s, fires due reminders via speech + push notification, supports daily/weekly recurrence via the API.
- All four background loops are wrapped in `try/except` — a single bad frame or transient error logs and continues instead of permanently killing the thread (this was a real bug fixed during development: an unhandled exception used to silently kill these loops forever until a full restart).

---

## ⚠️ Known Limitations

Being direct about what's *not* solid, so nobody assumes more than what's actually here:

- **`ai/autonomy.py` is dead code.** Nothing imports or calls it. It's a parallel, simpler follow-tracker implementation that predates the current `follow_me_loop()` in `app.py`. Either wire it in deliberately (it is NOT safe to run alongside `follow_me_loop()` as-is — no shared locking, will fight for motor control) or delete it.
- **Team-roster LCD cast doesn't work against current firmware.** `app.py` calls `/team` and `/show_member` on the ESP32; neither route exists in any `.ino` file in `firmware/esp32-dev/`. The call fails silently (caught exception), so nothing visibly breaks — the feature just never does anything.
- **`desktop_app.py`, `audio/stt.py`, `audio/tts.py`, `ai/mcp_server.py`, `memory/*`, `robot_runtime/*`** were not reviewed as part of this fix pass. Treat as unverified.
- **No dashboard UI for reminders** — voice and REST API only, no visual card yet.
- **No whole-home coverage.** Single camera, wherever the robot happens to be pointed. Not a substitute for dedicated room sensors if used for safety monitoring.
- **Elder-care fall-detection was deliberately not built** (scoped out during development) — patrol-mode sentry only fires with a person actively in camera view during active patrol, not passive monitoring.

---

## 🩺 Troubleshooting

**"Robot is offline"** → Confirm both ESP32 boards are powered and on the same WiFi as the server. IPs drift after DHCP renewal — update them on the Settings page rather than editing `.env` and restarting.

**Follow-me / patrol not moving** → Check the log for `[MOTION] Distance sensor read failed`. If present, `motion.get_distance()` is failing against the ESP32 `/distance` endpoint — verify connectivity before assuming a logic bug.

**Gesture mode unresponsive** → Confirm hand is well-lit and centered in the camera's forward-facing view; `min_detection_confidence=0.7` in `gesture_nav.py` is fairly strict for a low-quality ESP32-CAM feed.

**Choppy/garbled speaker audio** → If it correlates with motor activity, suspect shared power-rail interference between the motor driver and the I2S amp (separate their supplies or add a decoupling capacitor). If it happens with motors idle too, it's a streaming/software issue, not electrical.

**Alerts not arriving on phone** → Say "Jarvis, test alert" — it reports which channel(s) actually fired. Verify `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` or `NTFY_TOPIC` in `.env`.

**Repo is huge / has hundreds of stray `.mp3`/`.wav` files** → These were committed before `.gitignore` correctly matched the real generated filenames (fixed now). Run once to clean up:
```powershell
git rm -r --cached temp_tts_*.mp3 tts_*.mp3 robot_mic_*.wav jarvis_brain_db
git commit -m "Untrack generated runtime files"
```

---

## License

MIT — see `LICENSE`.
