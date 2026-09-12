import os
import re
import json
import time
import socket
import cv2
import requests
import psutil
import threading
from datetime import datetime
from dotenv import load_dotenv
from groq import Groq
from google import genai
from google.genai import types
from ollama import Client as OllamaClient
from jarvis.common.logger import setup_logger
from jarvis.memory.local_db import LocalDatabase
from jarvis.ai.memory import LongTermMemory
from jarvis.storage.cloud_manager import CloudManager

load_dotenv()
logger = setup_logger()

class JarvisBrain:
    def __init__(self, vision_pipeline=None):
        raw_esp_ip = os.getenv("ESP32_IP", "http://jarvis.local").strip().rstrip("/")
        self.esp32_ip = raw_esp_ip if raw_esp_ip.startswith("http") else f"http://{raw_esp_ip}"

        self.vision_pipeline = vision_pipeline
        self.cloud = CloudManager()

        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        if not self.groq_api_key:
            logger.warning("GROQ_API_KEY is missing from .env!")

        self.groq_client = Groq(api_key=self.groq_api_key)
        self.groq_model_primary = os.getenv("GROQ_MODEL_PRIMARY", "llama-3.3-70b-versatile")
        self.groq_model_secondary = os.getenv("GROQ_MODEL_SECONDARY", "gemma2-9b-it")

        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        if self.gemini_api_key:
            self.gemini_client = genai.Client(api_key=self.gemini_api_key)
        else:
            self.gemini_client = None

        self.tavily_api_key = os.getenv("TAVILY_API_KEY", "")

        self.ollama_client = OllamaClient(host="http://127.0.0.1:11434", timeout=30.0)
        self.local_model = os.getenv("OLLAMA_LOCAL_MODEL", "qwen2.5:3b")

        self.db = LocalDatabase()
        self.long_term_memory = LongTermMemory()

        self.tools = [
            {"type": "function", "function": {"name": "get_system_diagnostics", "description": "Get real-time host CPU usage, RAM utilization, and battery status.", "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "take_security_snapshot", "description": "Capture a live frame from ESP32-CAM and upload it to cloud storage.", "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "scan_environment", "description": "Ping the ultrasonic distance sensor to check for obstacle clearance.", "parameters": {"type": "object", "properties": {}}}}
        ]

        if self.tavily_api_key:
            self.tools.append({"type": "function", "function": {"name": "search_the_web", "description": "Search the live internet using Tavily for recent news, current events, or up-to-date facts.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}})

        logger.info(f"JarvisBrain initialized with Memory, Gemini & Agent Tools. ESP32 IP: {self.esp32_ip}")

    def set_esp32_emotion(self, emotion: str):
        if not self.esp32_ip: return
        try: requests.get(f"{self.esp32_ip}/emotion?type={emotion}", timeout=0.8)
        except Exception: pass

    def execute_tool(self, function_name: str, arguments: dict) -> str:
        logger.info(f"[AGENT TOOL] Executing: {function_name} with {arguments}")
        try:
            if function_name == "get_system_diagnostics":
                cpu = psutil.cpu_percent(interval=0.2)
                ram = psutil.virtual_memory().percent
                battery = psutil.sensors_battery()
                batt = f"{battery.percent}%" if battery else "AC Power"
                return json.dumps({"cpu_usage": f"{cpu}%", "ram_usage": f"{ram}%", "power_status": batt})
            elif function_name == "take_security_snapshot":
                if self.vision_pipeline:
                    frame = self.vision_pipeline.get_latest_frame()
                    if frame is not None:
                        success, buffer = cv2.imencode('.jpg', frame)
                        if success:
                            cloud_url = self.cloud.upload_snapshot(buffer.tobytes())
                            return json.dumps({"status": "success", "cloud_image_url": cloud_url})
                return json.dumps({"error": "Camera frame unavailable."})
            elif function_name == "scan_environment":
                try:
                    res = requests.get(f"{self.esp32_ip}/distance", timeout=1.5)
                    if res.status_code == 200:
                        dist = float(res.text)
                        return json.dumps({"front_distance_cm": dist, "status": "Clear" if dist > 30 else "Blocked"})
                except Exception as e: return json.dumps({"error": f"Sensor ping failed: {e}"})
            elif function_name == "search_the_web":
                query = arguments.get("query", "")
                if not query or not self.tavily_api_key: return json.dumps({"error": "Tavily missing."})
                try:
                    response = requests.post("https://api.tavily.com/search", json={"api_key": self.tavily_api_key, "query": query, "max_results": 3}, timeout=10)
                    response.raise_for_status()
                    results = response.json().get("results", [])
                    if not results: return json.dumps({"error": "No live results."})
                    search_data = "\n".join([f"- {res.get('title', '')}: {res.get('content', '')}" for res in results])
                    return json.dumps({"status": "success", "live_data": search_data})
                except Exception as e: return json.dumps({"error": str(e)})
            return json.dumps({"error": f"Unknown tool: {function_name}"})
        except Exception as e: return json.dumps({"error": str(e)})

    def _check_creator_query(self, user_text: str) -> tuple[bool, bool]:
        lower = user_text.lower()
        en_keywords = ["who made you", "who created you", "who built you", "team members", "your creators", "group 7", "group no 7"]
        if any(kw in lower for kw in en_keywords): return True, False
        hi_keywords = ["किसने बनाया", "तुम्हें किसने बनाया", "निर्माता", "kisne banaya", "tumhe kisne banaya"]
        if any(kw in lower for kw in hi_keywords): return True, True
        return False, False

    def _build_system_prompt(self, language_mode="en"):
        current_time = datetime.now().strftime("%I:%M %p on %A, %B %d, %Y")
        lang = "Speak in fluent Hindi or Hinglish." if language_mode == "hi" else "Respond concisely in English."
        return (
            f"You are JARVIS, an autonomous AI robot built by Group No. 7 under the guidance of Prof. P. V. Gupta Ma'am. "
            f"Your creators: Meet Bhavsar, Bhakti Nivgane, Shreya Shukla, Dhara Thakkar, Janvi Bhatt. "
            f"CRITICAL TEMPORAL DIRECTIVE: Host system time is {current_time}. You are operating in 2026. "
            f"If asked for current facts/news/scores, YOU MUST USE THE 'search_the_web' TOOL. "
            f"{lang} Keep responses natural, helpful, and concise (1-2 sentences)."
        )

    def diagnose(self) -> dict:
        return {"status": "ok", "cloud_active": True}

    def _extract_and_save_fact(self, user_text: str):
        if not self.gemini_client: return
        try:
            prompt = "Does this statement contain a personal fact, preference, or state of being about the user? If yes, reply ONLY with a concise factual sentence (e.g., 'User is feeling tired today', 'User likes coffee'). If no, reply ONLY with 'NONE'. Statement: " + user_text
            res = self.gemini_client.models.generate_content(model='gemini-3.6-flash', contents=prompt)
            fact = res.text.strip()
            if fact and "NONE" not in fact.upper():
                self.long_term_memory.remember(fact)
                logger.info(f"Proactively remembered: {fact}")
        except Exception: pass

    def _try_ollama(self, messages: list) -> str | None:
        """
        NEW: pulled the Ollama call out into its own helper so it can be
        tried FIRST (not just as a last-resort fallback) when the person has
        selected "Local Offline (Ollama)" as their preferred engine in
        Settings. Returns None on failure instead of a canned string, so the
        caller can decide what to fall back to.
        """
        try:
            clean_messages = [{"role": m["role"], "content": m["content"]} for m in messages if isinstance(m, dict) and "content" in m and m.get("role") != "tool"]
            res = self.ollama_client.chat(model=self.local_model, messages=clean_messages, options={"temperature": 0.3})
            content = res.get('message', {}).get('content', '').strip()
            return content or None
        except Exception as e:
            logger.warning(f"Ollama call failed: {e}")
            return None

    def think(self, user_input: str, language_mode: str = "en", engine_preference: str = "groq") -> str:
        """
        engine_preference: "groq" (default, cloud-first with local fallback)
        or "ollama" (local-first, only falls back to cloud if Ollama itself
        fails to respond -- e.g. not running / model not pulled).

        FIX: this parameter didn't exist before. The Settings page's
        "Primary AI Reasoning Engine" dropdown had a note admitting it was
        "not yet wired to actually switch engines" -- selecting Ollama did
        nothing; every request still went to Groq/Gemini first regardless.
        """
        self.set_esp32_emotion("thinking")
        logger.info(f"User input ({language_mode}, engine={engine_preference}): {user_input}")
        self.db.add_chat_message("user", user_input)

        threading.Thread(target=self._extract_and_save_fact, args=(user_input,), daemon=True).start()

        is_creator, is_hindi = self._check_creator_query(user_input)
        if is_creator:
            resp = "मुझे ग्रुप नंबर 7 ने प्रो. पी. वी. गुप्ता मैम के मार्गदर्शन में बनाया है!" if is_hindi or language_mode == "hi" else "I was engineered by Group No. 7 under the expert guidance of Prof. P. V. Gupta Ma'am."
            self.set_esp32_emotion("happy")
            self.db.add_chat_message("assistant", resp)
            return resp

        vision_keywords = ["what do you see", "look at", "what is in front", "scan the room", "camera"]
        if any(kw in user_input.lower() for kw in vision_keywords) and self.vision_pipeline and self.gemini_client:
            frame = self.vision_pipeline.get_latest_frame()
            if frame is not None:
                try:
                    success, buffer = cv2.imencode('.jpg', frame)
                    if success:
                        lang_instruction = "Respond natively in Hindi." if language_mode == "hi" else "Respond concisely in English."
                        gemini_res = self.gemini_client.models.generate_content(
                            model='gemini-3.6-flash',
                            contents=[types.Part.from_bytes(data=buffer.tobytes(), mime_type='image/jpeg'), f"{self._build_system_prompt(language_mode)} {lang_instruction} User asks: {user_input}"]
                        )
                        response_text = gemini_res.text.strip()
                        if response_text:
                            self.set_esp32_emotion("happy")
                            self.db.add_chat_message("assistant", response_text)
                            return response_text
                except Exception as e:
                    logger.warning(f"Gemini Vision call failed: {e}")

        visible_items = self.vision_pipeline.get_detected_labels() if self.vision_pipeline else []
        vision_context = f"[Visible objects: {', '.join(visible_items)}]\n" if visible_items else ""
        past_context = self.long_term_memory.recall(user_input)
        memory_injection = f"[Stored Memory context: {past_context}]\n" if past_context else ""

        full_user_prompt = f"{vision_context}{memory_injection}{user_input}"
        messages = [{"role": "system", "content": self._build_system_prompt(language_mode)}, *[{"role": role, "content": content} for role, content in self.db.get_recent_chat_history(limit=5)], {"role": "user", "content": full_user_prompt}]

        response_text, success = "", False

        # NEW: local-first path when the person picked "Local Offline
        # (Ollama)" in Settings. Note tool-calling (search_the_web, system
        # diagnostics, etc.) isn't available on this path since it goes
        # through the plain chat API, not the Groq tool-calling flow.
        if engine_preference == "ollama":
            local_result = self._try_ollama(messages)
            if local_result:
                response_text = local_result
                success = True
            else:
                logger.info("Ollama preferred but unavailable, falling back to cloud engines.")

        if not success:
            for model in [self.groq_model_primary, self.groq_model_secondary]:
                try:
                    chat_completion = self.groq_client.chat.completions.create(messages=messages, model=model, tools=self.tools, tool_choice="auto", temperature=0.3, max_tokens=400)
                    msg = chat_completion.choices[0].message
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        temp_messages = [dict(m) if isinstance(m, dict) else m for m in messages]
                        temp_messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [{"id": tc.id, "type": tc.type, "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in msg.tool_calls]})
                        for tc in msg.tool_calls:
                            args = json.loads(tc.function.arguments or "{}")
                            temp_messages.append({"tool_call_id": tc.id, "role": "tool", "name": tc.function.name, "content": self.execute_tool(tc.function.name, args)})
                        final_res = self.groq_client.chat.completions.create(model=model, messages=temp_messages, temperature=0.3, max_tokens=250)
                        response_text = final_res.choices[0].message.content
                    else: response_text = msg.content
                    if response_text:
                        success = True
                        break
                except Exception as e: logger.warning(f"Groq Cloud Model [{model}] Failed: {e}")

        if not success and self.gemini_client:
            try:
                prompt_text = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
                gemini_res = self.gemini_client.models.generate_content(model='gemini-3.6-flash', contents=prompt_text)
                response_text = gemini_res.text.strip()
                if response_text: success = True
            except Exception as e: logger.warning(f"Gemini Fallback Failed: {e}")

        if not success:
            # NEW: if engine_preference was already "ollama" we already tried
            # this above -- retrying identically here would just repeat the
            # same failure, so only try it now if we hadn't already.
            if engine_preference != "ollama":
                local_result = self._try_ollama(messages)
                if local_result:
                    response_text = local_result
                    success = True
            if not success:
                response_text = "Neural processors are temporarily offline, sir."
                self.set_esp32_emotion("confused")

        if "</think>" in response_text: response_text = response_text.split("</think>")[-1].strip()
        if success: self.set_esp32_emotion("happy")

        self.db.add_chat_message("assistant", response_text)
        return response_text
