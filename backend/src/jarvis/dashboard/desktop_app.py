import cv2
import random
import threading
import re
import customtkinter as ctk
from PIL import Image
from jarvis.common.logger import setup_logger
from jarvis.ai.vision import VisionPipeline
from jarvis.ai.brain import JarvisBrain
from jarvis.audio.tts import KokoroSpeaker
from jarvis.motion.motion_controller import MotionController

logger = setup_logger()

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class JarvisDesktopUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("JARVIS MINI V2 - Tactical Interface")
        self.geometry("1100x800")
        
        # Face & Speech States
        self.current_eye_color = "#00FFCC"
        self.is_speaking = False
        self.mouth_open = False
        
        # Initialize Core Systems
        logger.info("Starting Core Systems...")
        self.vision = VisionPipeline()
        self.vision.start_stream()
        
        self.brain = JarvisBrain()
        self.tts = KokoroSpeaker()
        self.motion = MotionController()
        
        # Configure grid layout
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        self.build_video_panel()
        self.build_control_panel()
        
        self.update_video_feed()
        self.schedule_blinking()

    def build_video_panel(self):
        self.video_frame = ctk.CTkFrame(self, corner_radius=10)
        self.video_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        
        self.video_label = ctk.CTkLabel(self.video_frame, text="LOADING VISION SYSTEM...", font=("Consolas", 24, "bold"))
        self.video_label.pack(expand=True, padx=10, pady=10)

    def build_control_panel(self):
        self.control_frame = ctk.CTkFrame(self, corner_radius=10)
        self.control_frame.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")

        # Telemetry Section
        ctk.CTkLabel(self.control_frame, text="SYSTEM TELEMETRY", font=("Consolas", 16, "bold")).pack(pady=(10, 5))
        self.status_label = ctk.CTkLabel(self.control_frame, text="Status: ONLINE", text_color="cyan")
        self.status_label.pack(anchor="w", padx=20, pady=2)

        # AI VOICE-SYNCED FACE SECTION
        ctk.CTkLabel(self.control_frame, text="AI VOICE-SYNCED FACE", font=("Consolas", 16, "bold")).pack(pady=(15, 5))
        
        self.eye_canvas = ctk.CTkCanvas(self.control_frame, width=220, height=90, bg="#000000", highlightthickness=1, highlightbackground="#333333")
        self.eye_canvas.pack(pady=5)
        self.draw_face(self.current_eye_color, blinking=False)

        # Color Selector Buttons
        color_frame = ctk.CTkFrame(self.control_frame, fg_color="transparent")
        color_frame.pack(pady=5)
        
        colors = [
            ("Cyan", "#00FFCC"),
            ("Red", "#FF3366"),
            ("Green", "#00FF66"),
            ("Yellow", "#FFCC00"),
            ("Blue", "#3399FF"),
            ("Purple", "#CC33FF")
        ]
        
        for name, hex_code in colors:
            btn = ctk.CTkButton(
                color_frame, text="", width=24, height=24, corner_radius=12,
                fg_color=hex_code, hover_color=hex_code,
                command=lambda c=hex_code: self.change_eye_color(c)
            )
            btn.pack(side="left", padx=4)

        # Motion Control Matrix Section
        ctk.CTkLabel(self.control_frame, text="MANUAL OVERRIDE", font=("Consolas", 16, "bold")).pack(pady=(15, 5))
        
        btn_grid = ctk.CTkFrame(self.control_frame, fg_color="transparent")
        btn_grid.pack(pady=5)
        
        ctk.CTkButton(btn_grid, text="▲", width=50, height=35, command=lambda: self.send_move("forward")).grid(row=0, column=1, padx=3, pady=3)
        ctk.CTkButton(btn_grid, text="◄", width=50, height=35, command=lambda: self.send_move("left")).grid(row=1, column=0, padx=3, pady=3)
        ctk.CTkButton(btn_grid, text="■", width=50, height=35, fg_color="darkred", hover_color="red", command=lambda: self.send_move("stop")).grid(row=1, column=1, padx=3, pady=3)
        ctk.CTkButton(btn_grid, text="►", width=50, height=35, command=lambda: self.send_move("right")).grid(row=1, column=2, padx=3, pady=3)
        ctk.CTkButton(btn_grid, text="▼", width=50, height=35, command=lambda: self.send_move("backward")).grid(row=2, column=1, padx=3, pady=3)

        # AI Assistant Terminal
        ctk.CTkLabel(self.control_frame, text="AI TERMINAL", font=("Consolas", 16, "bold")).pack(pady=(15, 5))
        
        self.chat_history = ctk.CTkTextbox(self.control_frame, height=100, state="disabled", font=("Consolas", 11))
        self.chat_history.pack(fill="x", padx=20, pady=5)
        self._append_to_chat("SYSTEM: Low-latency streaming interface online.\n")
        
        self.chat_input = ctk.CTkEntry(self.control_frame, placeholder_text="Ask JARVIS something...")
        self.chat_input.pack(fill="x", padx=20, pady=5)
        self.chat_input.bind("<Return>", self.handle_chat_input)

    def draw_face(self, color, blinking=False):
        self.eye_canvas.delete("all")
        if blinking:
            self.eye_canvas.create_line(35, 35, 95, 35, fill=color, width=4)
            self.eye_canvas.create_line(125, 35, 185, 35, fill=color, width=4)
        else:
            self.eye_canvas.create_polygon(35, 15, 95, 20, 85, 55, 35, 45, fill=color, outline="")
            self.eye_canvas.create_polygon(125, 20, 185, 15, 185, 45, 135, 55, fill=color, outline="")

        if self.is_speaking:
            if self.mouth_open:
                self.eye_canvas.create_rectangle(85, 68, 95, 82, fill=color, outline="")
                self.eye_canvas.create_rectangle(100, 62, 110, 85, fill=color, outline="")
                self.eye_canvas.create_rectangle(115, 68, 125, 82, fill=color, outline="")
            else:
                self.eye_canvas.create_rectangle(85, 73, 95, 77, fill=color, outline="")
                self.eye_canvas.create_rectangle(100, 70, 110, 80, fill=color, outline="")
                self.eye_canvas.create_rectangle(115, 73, 125, 77, fill=color, outline="")
        else:
            self.eye_canvas.create_line(90, 75, 130, 75, fill=color, width=3, capstyle="round")

    def animate_speaking(self):
        if not self.is_speaking:
            return
        self.mouth_open = not self.mouth_open
        self.draw_face(self.current_eye_color, blinking=False)
        self.after(120, self.animate_speaking)

    def schedule_blinking(self):
        def blink_sequence():
            if not self.is_speaking:
                self.draw_face(self.current_eye_color, blinking=True)
                self.after(150, lambda: self.draw_face(self.current_eye_color, blinking=False))
        delay = random.randint(3500, 7000)
        self.after(delay, blink_sequence)
        self.after(delay + 200, self.schedule_blinking)

    def change_eye_color(self, hex_color):
        self.current_eye_color = hex_color
        self.draw_face(hex_color, blinking=False)
        logger.info(f"Eye color changed to: {hex_color}")
        threading.Thread(target=self.motion.execute_eye_color, args=(
            int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
        )).start()

    def send_move(self, direction: str):
        result = self.motion.execute_movement(direction, duration=1.0)
        logger.info(f"Manual Command Sent: {direction} -> {result}")

    def handle_chat_input(self, event=None):
        user_text = self.chat_input.get().strip()
        if not user_text:
            return
        self.chat_input.delete(0, 'end')
        self._append_to_chat(f"You: {user_text}\n")
        threading.Thread(target=self._process_ai_response, args=(user_text,)).start()

    def _process_ai_response(self, text: str):
        try:
            # 1. Get response from local LLM brain
            response = self.brain.think(text)
            self.after(0, self._append_to_chat, f"JARVIS: {response}\n\n")
            
            # 2. Split response into sentences to stream audio piece-by-piece
            sentences = re.split(r'(?<=[.!?])\s+', response)
            
            self.is_speaking = True
            self.after(0, self.animate_speaking)
            
            # 3. Speak each sentence sequentially without waiting for the whole paragraph
            for sentence in sentences:
                if sentence.strip():
                    self.tts.speak(sentence.strip())
            
            self.is_speaking = False
            self.after(0, lambda: self.draw_face(self.current_eye_color, blinking=False))
            
        except Exception as e:
            logger.error(f"AI Error: {e}")
            self.is_speaking = False

    def _append_to_chat(self, text: str):
        self.chat_history.configure(state="normal")
        self.chat_history.insert("end", text)
        self.chat_history.yview("end")
        self.chat_history.configure(state="disabled")

    def update_video_feed(self):
        frame = self.vision.get_latest_frame()
        if frame is not None:
            frame = cv2.resize(frame, (640, 480))
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(frame_rgb)
            ctk_image = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=(640, 480))
            self.video_label.configure(image=ctk_image, text="")
        self.after(30, self.update_video_feed)

    def on_closing(self):
        logger.info("Shutting down...")
        self.vision.stop_stream()
        self.destroy()

if __name__ == "__main__":
    app = JarvisDesktopUI()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()