import os
import yaml
from ollama import Client as OllamaClient
from google import genai
from google.genai import types
from jarvis.common.logger import setup_logger
from jarvis.memory.local_db import LocalDatabase
from jarvis.robot_runtime.telemetry_manager import TelemetryManager

logger = setup_logger()

class JarvisBrain:
    def __init__(self):
        # Calculate root directory path (4 levels up from ai/)
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
        config_path = os.path.join(root_dir, "config", "cloud.yaml")
        
        with open(config_path, 'r') as file:
            self.config = yaml.safe_load(file)
            
        self.db = LocalDatabase()
        self.telemetry = TelemetryManager()
        
        # Local Ollama Setup (Configured for qwen2.5:3b or your active model)
        local_cfg = self.config.get('local_llm', {})
        self.local_model = local_cfg.get('model_name', 'qwen2.5:3b')
        self.ollama_client = OllamaClient(
            host=local_cfg.get('host', 'http://localhost:11434'),
            timeout=15.0  # Extended timeout for CPU inference
        )
        
        # Cloud Gemini Fallback Setup (Safely fetched without raising KeyError)
        self.use_cloud_fallback = self.config.get('cloud_llm', {}).get('enabled', False)
        if self.use_cloud_fallback:
            cloud_cfg = self.config.get('cloud_llm', {})
            api_key = os.getenv("GEMINI_API_KEY") or cloud_cfg.get('api_key', '')
            
            # Initialize Gemini Developer API Client
            self.gemini_client = genai.Client(api_key=api_key)
            self.gemini_model = cloud_cfg.get('model_name', 'gemini-2.5-flash')

    def _build_system_prompt(self):
        """Injects live vision context dynamically into the system prompt."""
        vision_context = self.telemetry.get_current_vision_context()
        if not vision_context:
            vision_context = "No objects currently detected."
            
        return (
            "You are JARVIS MINI, an AI robot assistant. "
            "CRITICAL INSTRUCTION: You DO have a camera and you CAN see. "
            f"RIGHT NOW, your camera sees: {vision_context}. "
            "If the user asks what you see, you must reply by listing those exact items concise and directly. "
            "NEVER say that you lack visual input or camera capabilities."
        )

    def _format_messages_for_ollama(self, system_prompt, history, new_prompt):
        messages = [{"role": "system", "content": system_prompt}]
        for role, content in history:
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": new_prompt})
        return messages

    def think(self, user_input: str) -> str:
        """Processes user input, queries LLM with live vision context, and logs conversation."""
        logger.info(f"User: {user_input}")
        self.db.add_chat_message("user", user_input)
        
        # Retrieve real-time vision telemetry
        vision_context = self.telemetry.get_current_vision_context()
        if not vision_context:
            vision_context = "nothing"
            
        augmented_prompt = f"{user_input}\n[SYSTEM NOTE: Your camera currently sees: {vision_context}. Base your visual response strictly on these items.]"
        
        system_prompt = self._build_system_prompt()
        history = self.db.get_recent_chat_history(limit=5)
        
        response_text = ""
        
        try:
            # 1. Attempt Local Inference via Ollama API (Temperature set to 0.2 for consistency)
            logger.debug(f"Attempting local inference with {self.local_model}...")
            messages = self._format_messages_for_ollama(system_prompt, history, augmented_prompt) 
            
            response = self.ollama_client.chat(
                model=self.local_model, 
                messages=messages,
                options={"temperature": 0.2}
            )
            response_text = response['message']['content']
            
        except Exception as e:
            logger.warning(f"Local Ollama failed: {e}.")
            
            # 2. Fallback to Gemini API if local fails and cloud fallback is enabled
            if self.use_cloud_fallback:
                logger.info(f"Falling back to Cloud Gemini ({self.gemini_model})...")
                try:
                    full_prompt = system_prompt + "\n\nChat History:\n" 
                    for r, c in history:
                        full_prompt += f"{r}: {c}\n"
                    full_prompt += f"\nUser: {augmented_prompt}"
                    
                    gemini_response = self.gemini_client.models.generate_content(
                        model=self.gemini_model, 
                        contents=full_prompt,
                        config=types.GenerateContentConfig(temperature=0.2)
                    )
                    response_text = gemini_response.text
                except Exception as cloud_e:
                    logger.error(f"Cloud fallback failed: {cloud_e}")
                    response_text = f"My neural link is re-establishing, but visually I can see: {vision_context}."
            else:
                response_text = "I am currently initializing my language model. Please try asking again in a moment."

        logger.info(f"JARVIS: {response_text}")
        self.db.add_chat_message("assistant", response_text)
        return response_text