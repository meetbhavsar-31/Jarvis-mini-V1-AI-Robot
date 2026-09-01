# 🤖 JARVIS MINI V2 — Master Tactical AI Robot

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-Computer%20Vision-5C3EE8?style=for-the-badge&logo=opencv&logoColor=white)
![ESP32](https://img.shields.io/badge/ESP32-Hardware%20Bridge-E7352C?style=for-the-badge&logo=espressif&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-VLM%20%26%20Whisper-F55036?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

<p align="center">
  <b>An autonomous, multi-modal robotics system powered by FastAPI, ESP32 microcontrollers, Groq Vision Language Models, and real-time biometric tracking.</b>
</p>

</div>

---

## 📑 Table of Contents
- [Project Overview](#-project-overview)
- [System Architecture](#-system-architecture)
- [Key Features](#-key-features)
- [Hardware & Hardware Pins](#-hardware--hardware-pins)
- [Directory Structure](#-directory-structure)
- [Installation & Setup](#-installation--setup)
- [Environment Configuration](#-environment-configuration)
- [Running the System](#-running-the-system)
- [API Reference](#-api-reference)
- [Autonomous Behaviors & Protocols](#-autonomous-behaviors--protocols)
- [Troubleshooting](#-troubleshooting)

---

## 🌟 Project Overview

**JARVIS MINI V2** is a modular robotics platform that bridges embedded hardware (ESP32 / ESP32-CAM) with cutting-edge Cloud & Local AI agents. The central server is written in **FastAPI** to enable:

- **Ultra-low latency streaming** via asynchronous WebSockets and MJPEG video feeds.
- **Natural Language Interaction** in multiple languages (English & Hindi) powered by Whisper-large-v3, Groq Qwen/Llama Vision pipelines, and local Ollama failover.
- **Biometric Face Tracking & Gesture Navigation** through OpenCV and MediaPipe.
- **Long-term Retrieval-Augmented Generation (RAG)** vector memory via ChromaDB.
- **Full Autonomous Roaming & Obstacle Avoidance** with automatic path recording and reverse-to-base capabilities.

---

## 🏗 System Architecture

```text
       ┌────────────────────────────────────────────────────────┐
       │                 JARVIS Brain (FastAPI)                 │
       │                                                        │
       │  ┌─────────────────┐  ┌─────────────────────────────┐  │
       │  │  Vision Pipeline│  │   Groq VLM / Whisper STT    │  │
       │  │  (Face/Gesture) │  │   & Local Ollama Fallback   │  │
       │  └────────┬────────┘  └──────────────┬──────────────┘  │
       │           │                          │                 │
       │  ┌────────┴────────┐  ┌──────────────┴──────────────┐  │
       │  │ ChromaDB Memory │  │ gTTS / Socket Audio Stream  │  │
       │  └─────────────────┘  └─────────────────────────────┘  │
       └───────────────────────────┬────────────────────────────┘
                                   │
                    HTTP REST / TCP Raw Audio / MJPEG
                                   │
         ┌─────────────────────────┴─────────────────────────┐
         │                                                   │
         ▼                                                   ▼
┌──────────────────┐                               ┌──────────────────┐
│   ESP32-S Node   │                               │    ESP32-CAM     │
│   (Locomotion,   │                               │  (Headless Vision│
│  Sensors, Eyes,  │                               │    Capture Node) │
│    Audio I/O)    │                               └──────────────────┘
└──────────────────┘