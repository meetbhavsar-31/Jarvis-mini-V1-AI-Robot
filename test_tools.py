import os
import sys
from dotenv import load_dotenv

# Tell Python to look inside the backend/src folder for the 'jarvis' package
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "backend", "src")))

load_dotenv()

from jarvis.ai.brain import JarvisBrain

def run_test():
    print("=" * 50)
    print("🛠️ TESTING JARVIS TOOL-CALLING & CLOUDINARY")
    print("=" * 50)

    brain = JarvisBrain()

    # 1. Test System Diagnostics Tool
    print("\n[TEST 1] Triggering System Diagnostics...")
    res1 = brain.think("What is your current CPU and RAM usage?")
    print(f"🤖 Jarvis: {res1}")

    # 2. Test Ultrasonic Sensor Ping Tool
    print("\n[TEST 2] Triggering Environment Scan...")
    res2 = brain.think("Scan the area in front of you. Is there any obstacle?")
    print(f"🤖 Jarvis: {res2}")

    # 3. Test Security Snapshot Upload Tool
    print("\n[TEST 3] Triggering Security Snapshot...")
    res3 = brain.think("Take a security snapshot and upload it.")
    print(f"🤖 Jarvis: {res3}")

    print("\n" + "=" * 50)
    print("✅ All Tool Inferences Dispatched!")
    print("=" * 50)

if __name__ == "__main__":
    run_test()