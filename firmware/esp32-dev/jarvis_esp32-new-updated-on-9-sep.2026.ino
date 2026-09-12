#include <WiFi.h>
#include <WebServer.h>
#include <WiFiManager.h>
#include <ESPmDNS.h> 
#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <SPI.h>
#include <driver/i2s.h>
#include <WiFiClient.h>
#include <HTTPClient.h>
#include <TJpg_Decoder.h>
#include "team_images.h"

// ==========================================
// TARGET PYTHON SERVER & DASHBOARD
// ==========================================
String pythonServerIP = ""; 
const int pythonServerPort = 8001; 
String dashboardServerAddress = "192.168.29.106:8000"; 

// ==========================================
// PIN DEFINITIONS 
// ==========================================
#define STATUS_LED 2
#define TFT_CS   16  
#define TFT_DC   17  
#define TFT_RST  -1  
#define TRIG_PIN 13
#define ECHO_PIN 14  
#define IN1 19  
#define IN2 21  
#define IN3 22  
#define IN4 4   
#define I2S_MIC_SCK 32
#define I2S_MIC_WS  33 
#define I2S_MIC_SD  34 
#define I2S_SPK_BCLK 26 
#define I2S_SPK_LRC  27 
#define I2S_SPK_DOUT 25 

Adafruit_ST7735 tft = Adafruit_ST7735(TFT_CS, TFT_DC, TFT_RST);
WebServer server(80);
WiFiServer audioServer(82); 

// ==========================================
// GLOBALS & STATE
// ==========================================
enum Emotion { THINKING, LISTENING, SURPRISE, SAD, HAPPY, ANGRY, SLEEPY, WINK, CONFUSED, TEAM_DISPLAY };
volatile Emotion currentEmotion = HAPPY;
Emotion previousEmotion = (Emotion)-1; 

bool isSpeaking = false;
bool mouthOpen = false;
unsigned long lastAnimTime = 0;
unsigned long lastBlinkTime = 0;
bool isBlinking = false;
uint16_t currentEyeColor = 0x07FF; 

volatile float currentDistanceCM = 100.0; 
String currentMovementDir = "stop";

// CONTINUOUS AUTONOMOUS STATE MACHINE
enum AutoState { SAFE_ZONE, WARNING_ZONE, DANGER_REVERSE, DANGER_TURN };
AutoState evadeState = SAFE_ZONE;
unsigned long evadeTimer = 0;
String evadeTurnDir = "right";

#define C_ORANGE 0xFD20
#define C_RED    0xF800
#define C_PURPLE 0x780F

#define MIC_PORT I2S_NUM_0
#define SPK_PORT I2S_NUM_1
#define BUFFER_LEN 1024
int16_t sBuffer[BUFFER_LEN];

void renderFace();
void playTone(int16_t amplitude, int duration_cycles);

// ==========================================
// JPEG DECODER CALLBACK
// ==========================================
bool tft_output(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t* bitmap) {
  if (y >= tft.height() || x >= tft.width()) return 0;
  tft.drawRGBBitmap(x, y, bitmap, w, h);
  return 1;
}

// ==========================================
// PWM MOTOR CONTROL (SPEED REGULATED)
// ==========================================
void setMotorPins(String dir) {
  int speed = 180; // 0 to 255 (180 = ~70% speed). Lower this if wheels still stutter.

  analogWrite(IN1, 0); analogWrite(IN2, 0); 
  analogWrite(IN3, 0); analogWrite(IN4, 0);

  if (dir == "forward") { 
    analogWrite(IN1, speed); // Right FWD
    analogWrite(IN3, speed); // Left FWD
  }
  else if (dir == "backward") { 
    analogWrite(IN2, speed); // Right BWD
    analogWrite(IN4, speed); // Left BWD
  }
  else if (dir == "left") { 
    analogWrite(IN1, speed); // Right FWD
    analogWrite(IN4, speed); // Left BWD
  }
  else if (dir == "right") { 
    analogWrite(IN2, speed); // Right BWD
    analogWrite(IN3, speed); // Left FWD
  }
  else if (dir == "forward_left") { 
    analogWrite(IN1, speed); // Right FWD Only
  }
  else if (dir == "forward_right") { 
    analogWrite(IN3, speed); // Left FWD Only
  }
  else if (dir == "backward_left") { 
    analogWrite(IN2, speed); // Right BWD Only
  }
  else if (dir == "backward_right") { 
    analogWrite(IN4, speed); // Left BWD Only
  }
}

void applyMotors(String dir) {
  currentMovementDir = dir;
  if (dir != "forward") {
    setMotorPins(dir);
    evadeState = SAFE_ZONE; 
  }
}

// ==========================================
// I2S AUDIO DRIVERS
// ==========================================
void i2s_mic_install() {
  const i2s_config_t i2s_config = {
    .mode = i2s_mode_t(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = 16000,
    .bits_per_sample = i2s_bits_per_sample_t(16),
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = 0,
    .dma_buf_count = 8,
    .dma_buf_len = BUFFER_LEN,
    .use_apll = false
  };
  i2s_driver_install(MIC_PORT, &i2s_config, 0, NULL);
  const i2s_pin_config_t pin_config = {
    .mck_io_num = I2S_PIN_NO_CHANGE, .bck_io_num = I2S_MIC_SCK,
    .ws_io_num = I2S_MIC_WS, .data_out_num = I2S_PIN_NO_CHANGE, .data_in_num = I2S_MIC_SD
  };
  i2s_set_pin(MIC_PORT, &pin_config);
  i2s_start(MIC_PORT);
}

void i2s_speaker_install() {
  const i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = 16000,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = 0,
    .dma_buf_count = 8,
    .dma_buf_len = 64,
    .use_apll = false
  };
  i2s_driver_install(SPK_PORT, &i2s_config, 0, NULL);
  const i2s_pin_config_t pin_config = {
    .mck_io_num = I2S_PIN_NO_CHANGE, .bck_io_num = I2S_SPK_BCLK,
    .ws_io_num = I2S_SPK_LRC, .data_out_num = I2S_SPK_DOUT, .data_in_num = I2S_PIN_NO_CHANGE
  };
  i2s_set_pin(SPK_PORT, &pin_config);
  i2s_start(SPK_PORT);
}

void playTone(int16_t amplitude, int duration_cycles) {
  size_t bytes_written;
  int16_t sample[2] = {amplitude, amplitude}; 
  for (int i = 0; i < duration_cycles; i++) {
    i2s_write(SPK_PORT, &sample, sizeof(sample), &bytes_written, portMAX_DELAY);
    sample[0] = -sample[0]; sample[1] = -sample[1]; 
  }
}

// ==========================================
// FREERTOS BACKGROUND TASKS
// ==========================================
void distanceTask(void * pvParameters) {
  while (true) {
    digitalWrite(TRIG_PIN, LOW); delayMicroseconds(2);
    digitalWrite(TRIG_PIN, HIGH); delayMicroseconds(10);
    digitalWrite(TRIG_PIN, LOW);
    
    long duration = pulseIn(ECHO_PIN, HIGH, 20000); 
    if (duration > 0) {
      float calculatedDist = (duration * 0.0343) / 2.0;
      if (calculatedDist >= 2.0 && calculatedDist <= 400.0) currentDistanceCM = calculatedDist;
    } else {
      currentDistanceCM = 100.0; 
    }

    // CONTINUOUS AUTONOMOUS EXPLORATION LOGIC
    if (currentMovementDir == "forward") {
      unsigned long now = millis();

      switch (evadeState) {
        case SAFE_ZONE:
          if (currentDistanceCM < 25.0) {
            evadeState = DANGER_REVERSE;
            evadeTimer = now;
            setMotorPins("backward");
            currentEmotion = ANGRY;
            playTone(18000, 400); 
          } else if (currentDistanceCM <= 45.0) {
            evadeState = WARNING_ZONE;
            setMotorPins("forward"); 
            currentEmotion = SURPRISE;
          } else {
            setMotorPins("forward"); 
            if (currentEmotion != HAPPY && currentEmotion != TEAM_DISPLAY) currentEmotion = HAPPY;
          }
          break;

        case WARNING_ZONE:
          if (currentDistanceCM < 25.0) {
            evadeState = DANGER_REVERSE;
            evadeTimer = now;
            setMotorPins("backward");
            currentEmotion = ANGRY;
            playTone(18000, 400);
          } else if (currentDistanceCM > 45.0) {
            evadeState = SAFE_ZONE;
            setMotorPins("forward");
            currentEmotion = HAPPY;
          } else {
            setMotorPins("forward");
          }
          break;

        case DANGER_REVERSE:
          if (now - evadeTimer > 250) {
            evadeState = DANGER_TURN;
            evadeTurnDir = (millis() % 2 == 0) ? "left" : "right"; 
            setMotorPins(evadeTurnDir); 
            evadeTimer = now;
          }
          break;

        case DANGER_TURN:
          if (currentDistanceCM > 45.0) {
            evadeState = SAFE_ZONE;
            setMotorPins("forward");
            currentEmotion = HAPPY;
          } else {
            if (now - evadeTimer > 1500) {
              evadeState = DANGER_REVERSE; 
              evadeTimer = now;
              setMotorPins("backward");
            } else {
              setMotorPins(evadeTurnDir); 
            }
          }
          break;
      }
    } 
    vTaskDelay(pdMS_TO_TICKS(20)); 
  }
}

void audioMicTask(void * pvParameters) {
  i2s_mic_install();
  WiFiClient client;
  while (true) {
    if (WiFi.status() == WL_CONNECTED && pythonServerIP != "") {
      if (!client.connected()) client.connect(pythonServerIP.c_str(), pythonServerPort);
      if (client.connected()) {
        size_t bytesIn = 0;
        if (i2s_read(MIC_PORT, &sBuffer, BUFFER_LEN * sizeof(int16_t), &bytesIn, portMAX_DELAY) == ESP_OK && bytesIn > 0) {
          client.write((uint8_t*)sBuffer, bytesIn);
        }
      }
    }
    vTaskDelay(10 / portTICK_PERIOD_MS); 
  }
}

void audioPlaybackTask(void * pvParameters) {
  audioServer.begin();
  uint8_t buf[1024];
  while (true) {
    WiFiClient client = audioServer.available();
    if (client) {
      isSpeaking = true; 
      while (client.connected()) {
        int avail = client.available();
        if (avail >= 4) {
          int bytesToRead = (avail / 4) * 4; 
          if (bytesToRead > 1024) bytesToRead = 1024; 
          int len = client.read(buf, bytesToRead);
          size_t bw; i2s_write(SPK_PORT, buf, len, &bw, portMAX_DELAY);
        } else vTaskDelay(2 / portTICK_PERIOD_MS); 
      }
      client.stop();
      isSpeaking = false;
    }
    vTaskDelay(20 / portTICK_PERIOD_MS); 
  }
}

// ==========================================
// TFT DRAWING ROUTINES (160x128 Widescreen Center)
// ==========================================
void drawListening() {
  tft.drawCircle(40, 50, 20, currentEyeColor); tft.drawCircle(40, 50, 10, currentEyeColor);
  tft.drawCircle(120, 50, 20, currentEyeColor); tft.drawCircle(120, 50, 10, currentEyeColor);
  tft.drawLine(65, 80, 95, 80, currentEyeColor); tft.drawLine(75, 75, 75, 85, currentEyeColor); tft.drawLine(85, 70, 85, 90, currentEyeColor);
}
void drawThinking() {
  for (int i = 0; i < 360; i += 30) {
    int x = 80 + 30 * cos(i * PI / 180.0); int y = 50 + 30 * sin(i * PI / 180.0); tft.fillCircle(x, y, 2, C_ORANGE);
  }
  tft.drawCircle(80, 50, 8, C_ORANGE); tft.drawLine(85, 55, 95, 65, C_ORANGE); 
}
void drawSurprise() {
  tft.fillCircle(40, 50, 20, ST7735_WHITE); tft.fillCircle(40, 50, 15, ST7735_BLACK);
  tft.fillCircle(120, 50, 20, ST7735_WHITE); tft.fillCircle(120, 50, 15, ST7735_BLACK);
  tft.drawTriangle(80, 75, 70, 95, 90, 95, C_ORANGE);
}
void drawSad() {
  tft.drawCircleHelper(40, 60, 20, 1, currentEyeColor); tft.drawCircleHelper(120, 60, 20, 2, currentEyeColor);
  tft.drawCircleHelper(80, 100, 25, 3, currentEyeColor);
}
void drawHappy() {
  tft.drawCircle(40, 45, 15, currentEyeColor); tft.drawCircle(40, 45, 5, currentEyeColor);
  tft.drawCircle(120, 45, 15, currentEyeColor); tft.drawCircle(120, 45, 5, currentEyeColor);
  tft.drawFastHLine(65, 75, 30, currentEyeColor); 
}
void drawAngry() {
  tft.drawRect(5, 5, 150, 118, C_RED); 
  tft.drawLine(30, 40, 55, 55, C_RED); tft.drawLine(130, 40, 105, 55, C_RED);
  tft.drawFastHLine(65, 80, 30, C_RED);
}
void drawSleepy() {
  tft.fillRect(30, 60, 30, 4, currentEyeColor); tft.fillRect(100, 60, 30, 4, currentEyeColor);
  tft.drawRect(70, 90, 20, 10, ST7735_WHITE); tft.fillRect(72, 92, 5, 6, C_RED);
}
void drawWink() {
  tft.drawCircle(40, 50, 20, currentEyeColor); tft.drawCircle(40, 50, 10, currentEyeColor);
  tft.drawFastHLine(105, 50, 30, currentEyeColor); tft.drawFastHLine(65, 75, 30, currentEyeColor);
}
void drawConfused() {
  tft.setCursor(60, 30); tft.setTextColor(C_PURPLE); tft.setTextSize(6); tft.print("?");
}

void renderFace() {
  tft.fillScreen(ST7735_BLACK);
  if (currentEmotion != TEAM_DISPLAY) {
    tft.setCursor(5, 5); tft.setTextColor(ST7735_WHITE); tft.setTextSize(1); tft.print("JARVIS MINI V1");
    tft.setCursor(115, 5); tft.setTextColor(currentEyeColor); tft.print("ACTIVE");
  }
  
  switch (currentEmotion) {
    case THINKING:  drawThinking(); break;
    case LISTENING: drawListening(); break;
    case SURPRISE:  drawSurprise(); break;
    case SAD:       drawSad(); break;
    case HAPPY:     drawHappy(); break;
    case ANGRY:     drawAngry(); break;
    case SLEEPY:    drawSleepy(); break;
    case WINK:      drawWink(); break;
    case CONFUSED:  drawConfused(); break;
  }
  previousEmotion = currentEmotion;
}

// ==========================================
// TEAM PROFILE DISPLAY
// ==========================================
void showHardcodedProfile(const uint16_t* imgData, String name, String role, int hold_ms) {
  tft.fillScreen(ST7735_BLACK);
  tft.drawRGBBitmap(16, 0, imgData, 128, 128);  // centered on 160-wide landscape screen

  tft.fillRect(16, 108, 128, 20, ST7735_BLACK);
  tft.setCursor(20, 110); tft.setTextColor(ST7735_WHITE); tft.setTextSize(1); tft.print(name);
  tft.setCursor(20, 118); tft.setTextColor(C_ORANGE); tft.print(role);

  delay(hold_ms);
}

void processTeamDisplaySequence() {
  currentEmotion = TEAM_DISPLAY;

  showHardcodedProfile(meet_img,   "Meet Bhavsar",   "Lead & Firmware",   3000);
  showHardcodedProfile(bhakti_img, "Bhakti Nivgane", "Hardware & Power",  3000);
  showHardcodedProfile(shreya_img, "Shreya Shukla",  "AI & Backend Data", 3000);
  showHardcodedProfile(dhara_img,  "Dhara Thakkar",  "Vision & Tracking", 3000);
  showHardcodedProfile(janvi_img,  "Janvi Bhatt",    "Audio & Dashboard", 3000);

  currentEmotion = HAPPY;
  renderFace();
}

const uint16_t* imageForName(String name) {
  name.toLowerCase();
  if (name.indexOf("meet") >= 0)   return meet_img;
  if (name.indexOf("bhakti") >= 0) return bhakti_img;
  if (name.indexOf("shreya") >= 0) return shreya_img;
  if (name.indexOf("dhara") >= 0)  return dhara_img;
  if (name.indexOf("janvi") >= 0)  return janvi_img;
  return meet_img; 
}

void updateAnimations() {
  if (currentEmotion == TEAM_DISPLAY) return; 

  unsigned long currentMillis = millis();
  static bool wasSpeaking = false;
  
  if (isSpeaking && (currentEmotion == HAPPY || currentEmotion == LISTENING)) {
    wasSpeaking = true;
    if (currentMillis - lastAnimTime > 150) {
      lastAnimTime = currentMillis;
      mouthOpen = !mouthOpen;
      tft.fillRect(65, 70, 30, 20, ST7735_BLACK);
      if (mouthOpen) tft.fillRoundRect(70, 75, 20, 10, 3, currentEyeColor);
      else tft.drawFastHLine(70, 80, 20, currentEyeColor);
    }
  } else if (wasSpeaking) {
    wasSpeaking = false;
    tft.fillRect(65, 70, 30, 20, ST7735_BLACK);
    renderFace();
  }
  
  if (!isBlinking && (currentMillis - lastBlinkTime > random(3500, 7500)) && (currentEmotion != ANGRY)) {
    isBlinking = true;
    lastBlinkTime = currentMillis;
    tft.fillRect(20, 35, 120, 30, ST7735_BLACK);
    tft.drawFastHLine(30, 50, 25, currentEyeColor);
    tft.drawFastHLine(105, 50, 25, currentEyeColor);
  } else if (isBlinking && (currentMillis - lastBlinkTime > 150)) {
    isBlinking = false;
    renderFace();
  }
}

// ==========================================
// HTTP ENDPOINTS
// ==========================================
void handleSetServer() {
  if (server.hasArg("ip")) {
    pythonServerIP = server.arg("ip");
    server.send(200, "text/plain", "OK");
  } else server.send(400, "text/plain", "Missing IP");
}

void handleEmotion() {
  if (server.hasArg("type")) {
    String state = server.arg("type"); state.toLowerCase();
    if (state == "thinking") currentEmotion = THINKING; 
    else if (state == "listening") currentEmotion = LISTENING;
    else if (state == "surprise") currentEmotion = SURPRISE; 
    else if (state == "sad") currentEmotion = SAD;
    else if (state == "happy") currentEmotion = HAPPY; 
    else if (state == "angry") currentEmotion = ANGRY;
    else if (state == "sleepy") currentEmotion = SLEEPY; 
    else if (state == "wink") currentEmotion = WINK;
    else if (state == "confused") currentEmotion = CONFUSED;
    renderFace(); server.send(200, "text/plain", "OK");
  } else server.send(400, "text/plain", "Missing type");
}

void handleTeamDisplay() {
  if (server.hasArg("server")) {
    dashboardServerAddress = server.arg("server");
  }
  server.send(200, "text/plain", "Showing hardcoded team roster...");
  processTeamDisplaySequence();
}

void handleShowMember() {
  String name = server.hasArg("name") ? server.arg("name") : "Member";
  String role = server.hasArg("role") ? server.arg("role") : "Contributor";

  server.send(200, "text/plain", "Showing member: " + name);

  currentEmotion = TEAM_DISPLAY;
  showHardcodedProfile(imageForName(name), name, role, 4000);
  currentEmotion = HAPPY;
  renderFace();
}

void handleTalk() {
  if (server.hasArg("state")) {
    isSpeaking = (server.arg("state") == "on");
    if (!isSpeaking) { tft.fillRect(65, 70, 30, 20, ST7735_BLACK); renderFace(); }
    server.send(200, "text/plain", "OK");
  } else server.send(400, "text/plain", "Missing state");
}

void handleEyes() {
  if (server.hasArg("r") && server.hasArg("g") && server.hasArg("b")) {
    currentEyeColor = tft.color565(server.arg("r").toInt(), server.arg("g").toInt(), server.arg("b").toInt());
    renderFace(); server.send(200, "text/plain", "OK");
  } else server.send(400, "text/plain", "Missing RGB");
}

void handleMove() {
  if (server.hasArg("dir")) {
    applyMotors(server.arg("dir").c_str());
    server.send(200, "text/plain", "OK");
  } else server.send(400, "text/plain", "Error");
}

void handleDistance() { server.send(200, "text/plain", String(currentDistanceCM, 1)); }
void handleBeep() { playTone(15000, 2000); server.send(200, "text/plain", "Beeped"); }

void setup() {
  Serial.begin(115200);
  
  pinMode(STATUS_LED, OUTPUT); digitalWrite(STATUS_LED, HIGH);
  pinMode(TRIG_PIN, OUTPUT); pinMode(ECHO_PIN, INPUT);

  i2s_speaker_install();

  SPI.begin(18, -1, 23, -1);
  tft.initR(INITR_BLACKTAB);
  tft.setRotation(1);
  tft.fillScreen(ST7735_BLACK);

  TJpgDec.setJpgScale(2); 
  TJpgDec.setSwapBytes(true); 
  TJpgDec.setCallback(tft_output);

  pinMode(IN1, OUTPUT); analogWrite(IN1, 0); pinMode(IN2, OUTPUT); analogWrite(IN2, 0);
  pinMode(IN3, OUTPUT); analogWrite(IN3, 0); pinMode(IN4, OUTPUT); analogWrite(IN4, 0);

  // ==========================================
  // NEW CINEMATIC BOOT ANIMATION
  // ==========================================
  tft.fillScreen(ST7735_BLACK);
  
  // Tactical HUD brackets
  tft.drawLine(5, 5, 20, 5, ST7735_WHITE); tft.drawLine(5, 5, 5, 20, ST7735_WHITE);
  tft.drawLine(155, 5, 140, 5, ST7735_WHITE); tft.drawLine(155, 5, 155, 20, ST7735_WHITE);
  tft.drawLine(5, 123, 20, 123, ST7735_WHITE); tft.drawLine(5, 123, 5, 108, ST7735_WHITE);
  tft.drawLine(155, 123, 140, 123, ST7735_WHITE); tft.drawLine(155, 123, 155, 108, ST7735_WHITE);

  // Core Headers
  tft.setCursor(55, 15); tft.setTextColor(C_ORANGE); tft.setTextSize(1); tft.print("GROUP 7");
  tft.setCursor(35, 30); tft.setTextColor(ST7735_CYAN); tft.setTextSize(2); tft.print("JARVIS");
  
  // Terminal Boot Sequence Simulator
  tft.setTextSize(1);
  tft.setTextColor(ST7735_GREEN);
  String bootLogs[] = {"Initialize Core...", "Load Neural Net...", "Mount Drive...", "Connect Comm..."};
  int y_pos = 55;
  
  for(int j = 0; j < 4; j++) {
    tft.setCursor(15, y_pos);
    tft.print("> " + bootLogs[j]);
    playTone(8000 + (j * 2000), 200);
    delay(300);
    
    tft.setTextColor(ST7735_WHITE);
    tft.setCursor(120, y_pos);
    tft.print("[OK]");
    y_pos += 10;
    tft.setTextColor(ST7735_GREEN);
  }

  tft.setCursor(20, 100); tft.setTextColor(ST7735_YELLOW); tft.print("NEURAL LINK BOOTING");

  // Fast loading bar sweep
  tft.drawRect(15, 112, 130, 6, ST7735_BLUE);
  for (int i = 0; i <= 126; i += 6) { 
    tft.fillRect(17, 114, i, 2, ST7735_CYAN); 
    delay(40); 
  }
  
  playTone(15000, 1500); // Final success chime
  delay(500);
  // ==========================================

  WiFiManager wifiManager;
  wifiManager.autoConnect("JARVIS_Setup");

  if (MDNS.begin("jarvis")) Serial.println("mDNS started: http://jarvis.local");

  server.on("/set_server", HTTP_GET, handleSetServer);
  server.on("/emotion", HTTP_GET, handleEmotion);
  server.on("/team", HTTP_GET, handleTeamDisplay); 
  server.on("/show_member", HTTP_GET, handleShowMember); 
  server.on("/talk", HTTP_GET, handleTalk);
  server.on("/eyes", HTTP_GET, handleEyes);
  server.on("/move", HTTP_GET, handleMove);
  server.on("/distance", HTTP_GET, handleDistance);
  server.on("/beep", HTTP_GET, handleBeep);
  server.begin();

  renderFace();
  playTone(15000, 2000);

  xTaskCreatePinnedToCore(audioMicTask, "AudioTask", 10000, NULL, 1, NULL, 0);
  xTaskCreatePinnedToCore(audioPlaybackTask, "AudioPlayback", 10000, NULL, 1, NULL, 0);
  xTaskCreatePinnedToCore(distanceTask, "DistTask", 4096, NULL, 1, NULL, 0); 
}

void loop() {
  server.handleClient();
  updateAnimations();
  delay(2);
}