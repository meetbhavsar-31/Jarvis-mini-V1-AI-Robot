import cv2
import numpy as np
import requests
from ultralytics import YOLO

print("1. Loading YOLO11 model...")
model = YOLO("yolo11n.pt") 

# Your exact camera IP
stream_url = "http://192.168.29.175/stream" 

print(f"2. Connecting to {stream_url} as Google Chrome...")

try:
    # Disguise Python as a standard web browser
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    
    # Open the stream using requests
    response = requests.get(stream_url, stream=True, timeout=10, headers=headers)
    
    if response.status_code == 200:
        print("\n3. Stream connected! Running YOLO11. Press 'q' in the video window to quit.")
        bytes_data = bytes()
        
        for chunk in response.iter_content(chunk_size=1024):
            bytes_data += chunk
            a = bytes_data.find(b'\xff\xd8')
            b = bytes_data.find(b'\xff\xd9')
            
            if a != -1 and b != -1:
                jpg = bytes_data[a:b+2]
                bytes_data = bytes_data[b+2:]
                
                frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                
                if frame is not None:
                    results = model(frame)
                    annotated_frame = results[0].plot()
                    cv2.imshow("YOLO11 ESP32-CAM Test", annotated_frame)
                    
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
    else:
        print(f"Connection failed with status code: {response.status_code}")

except Exception as e:
    print(f"\n[CRITICAL ERROR] Could not connect: {e}")

cv2.destroyAllWindows()