import cv2
import numpy as np
import requests
import base64
import os
from groq import Groq

# ==========================================
# CONFIGURATION
# ==========================================
GROQ_API_KEY = "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"  # Put your API key here
STREAM_URL = "http://192.168.29.175/stream" 

os.environ["GROQ_API_KEY"] = GROQ_API_KEY
# ==========================================

def capture_frame(url, max_retries=3):
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    for attempt in range(1, max_retries + 1):
        try:
            print(f"Attempt {attempt}: Connecting to ESP32-CAM...")
            response = requests.get(url, stream=True, timeout=5, headers=headers)
            
            if response.status_code == 200:
                bytes_data = bytes()
                for chunk in response.iter_content(chunk_size=1024):
                    bytes_data += chunk
                    a = bytes_data.find(b'\xff\xd8')
                    b = bytes_data.find(b'\xff\xd9')
                    
                    if a != -1 and b != -1:
                        jpg = bytes_data[a:b+2]
                        frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                        response.close()
                        return frame
            response.close()
        except requests.exceptions.RequestException:
            print(f"Attempt {attempt} dropped a frame. Retrying...")
            
    return None

print("1. Initiating Frame Capture...")
frame_captured = capture_frame(STREAM_URL)

if frame_captured is not None:
    print("2. Valid frame acquired! Sending to Groq AI...")
    
    # Encode frame to Base64
    _, buffer = cv2.imencode('.jpg', frame_captured)
    base64_image = base64.b64encode(buffer).decode('utf-8')
    
    client = Groq()
    
    completion = client.chat.completions.create(
        model="qwen/qwen3.6-27b",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "You are JARVIS. Describe what you see in this image in one concise sentence."
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ]
    )
    
    # Strip out internal reasoning tags for a clean output
    answer = completion.choices[0].message.content
    if "</think>" in answer:
        answer = answer.split("</think>")[-1].strip()
        
    print("\n========================================")
    print("JARVIS SAYS:", answer)
    print("========================================\n")
else:
    print("[ERROR] Could not grab a valid frame from camera after multiple attempts.")