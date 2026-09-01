import os
import json
import time
import cv2
import requests
import psutil
from dotenv import load_dotenv
from groq import Groq
from ollama import Client as OllamaClient
from jarvis.common.logger import setup_logger
from jarvis.memory.local_db import LocalDatabase
from jarvis.ai.memory import LongTermMemory
from jarvis.storage.cloud_manager import CloudManager

# Load environment variables from the .env file in your root folder
load_dotenv()

logger = setup_logger()


class JarvisBrain:
    def __init__(self, vision_pipeline=None):
        # 1. Load ESP32 Display URL from .env
        raw_esp_ip = os.getenv("ESP32_IP", "http://jarvis.local").strip().rstrip("/")
        self.esp32_ip = raw_esp_ip if raw_esp_ip.startswith("http") else f"http://{raw_esp_ip}"

        # 2. Hardware and Storage References
        self.vision_pipeline = vision_pipeline
        self.cloud = CloudManager()

        # 3. Initialize Groq (Primary Cloud Brain)
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        if not self.groq_api_key:
            logger.warning("GROQ_API_KEY is missing from the .env file!")
            
        self.groq_client = Groq(api_key=self.groq_api_key)
        self.groq_model = "llama-3.3-70b-versatile"

        # 4. Initialize Ollama (Local Fallback Brain)
        self.ollama_client = OllamaClient(host="http://localhost:11434", timeout=15.0)
        self.local_model = "qwen2.5:3b"

        # 5. Initialize Memory Systems
        self.db = LocalDatabase()
        self.long_term_memory = LongTermMemory()
        
        # -----------------------------------------------------
        # FUNCTION REGISTRY (Agent Tools)
        # -----------------------------------------------------
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_system_diagnostics",
                    "description": "Get real-time host CPU usage, RAM utilization, and battery or power status.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "take_security_snapshot",
                    "description": "Capture a live frame from ESP32-CAM and upload it directly to cloud storage.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "scan_environment",
                    "description": "Ping the ultrasonic distance sensor to check for obstacle distance in front of the robot.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        logger.info(f"JarvisBrain initialized with Tools. ESP32 IP: {self.esp32_ip}")

    def set_esp32_emotion(self, emotion: str):
        """Helper to send non-blocking HTTP requests to update ESP32 screen emotion."""
        if not self.esp32_ip:
            return
        try:
            url = f"{self.esp32_ip}/emotion?type={emotion}"
            requests.get(url, timeout=0.8)
        except Exception as e:
            logger.debug(f"Could not send emotion '{emotion}' to ESP32: {e}")

    def execute_tool(self, function_name: str, arguments: dict) -> str:
        """Executes mapped hardware/system functions and returns structured JSON."""
        logger.info(f"[AGENT TOOL] Executing: {function_name}")
        
        try:
            if function_name == "get_system_diagnostics":
                cpu = psutil.cpu_percent(interval=0.3)
                ram = psutil.virtual_memory().percent
                battery = psutil.sensors_battery()
                batt = f"{battery.percent}%" if battery else "AC Desktop Power"
                return json.dumps({
                    "cpu_usage": f"{cpu}%",
                    "ram_usage": f"{ram}%",
                    "power_status": batt
                })

            elif function_name == "take_security_snapshot":
                if self.vision_pipeline:
                    frame = self.vision_pipeline.get_latest_frame()
                    if frame is not None:
                        success, buffer = cv2.imencode('.jpg', frame)
                        if success:
                            cloud_url = self.cloud.upload_snapshot(buffer.tobytes())
                            return json.dumps({
                                "status": "success",
                                "cloud_image_url": cloud_url
                            })
                return json.dumps({"error": "Camera stream frame is currently unavailable."})

            elif function_name == "scan_environment":
                try:
                    res = requests.get(f"{self.esp32_ip}/distance", timeout=2.0)
                    if res.status_code == 200:
                        dist = float(res.text)
                        status = "Path clear" if dist > 30 else "Obstacle blocking path"
                        return json.dumps({"front_distance_cm": dist, "status": status})
                except Exception as e:
                    return json.dumps({"error": f"Distance sensor ping failed: {e}"})

            return json.dumps({"error": f"Unknown tool: {function_name}"})
                
        except Exception as e:
            logger.error(f"Tool execution failure: {e}")
            return json.dumps({"error": str(e)})

    def _build_system_prompt(self, language_mode="en"):
        if language_mode == "hi":
            lang_instruction = "You are JARVIS, an advanced AI robot assistant. Speak in fluent Hindi or Hinglish."
        else:
            lang_instruction = "You are JARVIS, an advanced AI robot assistant. Respond concisely in English."
        
        return (
            f"{lang_instruction} "
            "Be polite, helpful, and concise (1-2 short sentences). "
            "You have direct access to physical robot and host tools. "
            "If the user asks for CPU/RAM/system stats, taking a snapshot/photo, or distance/sensor scans, use the appropriate tool. "
            "If visual context is provided in the prompt, use it to answer visual questions."
        )

    def think(self, user_input: str, language_mode: str = "en") -> str:
        # Trigger 'thinking' screen state immediately when processing starts
        self.set_esp32_emotion("thinking")

        logger.info(f"User ({language_mode}): {user_input}")
        self.db.add_chat_message("user", user_input)
        
        past_context = self.long_term_memory.recall(user_input)
        memory_injection = f"[Past Memory: {past_context}]\n" if past_context else ""
        
        full_user_prompt = f"{memory_injection}{user_input}"
        system_prompt = self._build_system_prompt(language_mode)
        
        history = self.db.get_recent_chat_history(limit=5)
        
        messages = [{"role": "system", "content": system_prompt}]
        for role, content in history:
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": full_user_prompt})

        response_text = ""
        success = False

        # --- ATTEMPT 1: GROQ (CLOUD PRIMARY WITH AGENT TOOLS) ---
        try:
            logger.debug("Attempting inference via Groq Cloud...")
            chat_completion = self.groq_client.chat.completions.create(
                messages=messages,
                model=self.groq_model,
                tools=self.tools,
                tool_choice="auto",
                temperature=0.3,
                max_tokens=500,
            )
            
            msg = chat_completion.choices[0].message
            tool_calls = msg.tool_calls

            # Handle Tool Calls
            if tool_calls:
                messages.append(msg)
                for tool_call in tool_calls:
                    fn_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                    
                    tool_output = self.execute_tool(fn_name, fn_args)

                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": fn_name,
                        "content": tool_output,
                    })

                # Follow-up completion after tool execution
                final_res = self.groq_client.chat.completions.create(
                    model=self.groq_model,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=300
                )
                response_text = final_res.choices[0].message.content
            else:
                response_text = msg.content

            success = True
            logger.info("Groq Cloud inference successful.")
        except Exception as groq_error:
            logger.warning(f"Groq Cloud failed or rate limited ({groq_error}). Falling back to local Ollama model...")

        # --- ATTEMPT 2: OLLAMA (LOCAL FAILOVER) ---
        if not success:
            try:
                logger.debug(f"Attempting local inference with {self.local_model} via Ollama...")
                # Filter out raw tool call dictionaries for simple Ollama chat
                clean_messages = [
                    {"role": m["role"], "content": m["content"]}
                    for m in messages if isinstance(m, dict) and "content" in m and m.get("role") != "tool"
                ]
                
                ollama_response = self.ollama_client.chat(
                    model=self.local_model,
                    messages=clean_messages,
                    options={"temperature": 0.3}
                )
                response_text = ollama_response['message']['content']
                success = True
                logger.info("Local Ollama failover inference successful.")
            except Exception as ollama_error:
                logger.error(f"Both Groq and Local Ollama failed: {ollama_error}")
                response_text = "Primary cloud and local neural links are currently unavailable, sir."
                self.set_esp32_emotion("confused")

        # Clean reasoning tags if local model includes them
        if response_text and "</think>" in response_text:
            response_text = response_text.split("</think>")[-1].strip()

        # Save memory if user specifies preferences
        lower_input = user_input.lower()
        if any(keyword in lower_input for keyword in ["remember", "my name is", "favorite"]):
            self.long_term_memory.remember(user_input)

        # Trigger 'happy' screen state when response is successfully generated
        if success:
            self.set_esp32_emotion("happy")

        logger.info(f"JARVIS: {response_text}")
        self.db.add_chat_message("assistant", response_text)
        return response_text