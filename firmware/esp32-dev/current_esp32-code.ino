// remove You want to revert the complex continuous-exploration "State Machine" and go back to your original, straightforward evasion logic:

// Drive forward.

// If an obstacle is detected (< 35cm), lock the controls (isEvading = true).

// Back up for 150ms.

// Turn right for 800ms.

// STOP and wait for the next command.

// I have ripped out the continuous looping state machine and put your exact requested motor and evasion logic back in.

// Crucially, I kept the malloc image buffer fix and the 160x128 screen coordinate adjustments, so the team photos will still load perfectly without crashing the robot.

// Here is your final, tailored ESP32 code:

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
volatile bool isEvading = false; 

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
// MOTOR CONTROL HELPER (Your Original Logic)
// ==========================================
void applyMotors(String dir) {
  currentMovementDir = dir;
  
  digitalWrite(IN1, LOW); 
  digitalWrite(IN2, LOW); 
  digitalWrite(IN3, LOW); 
  digitalWrite(IN4, LOW);

  if (dir == "forward") { 
    digitalWrite(IN1, HIGH); 
    digitalWrite(IN3, HIGH); 
  }
  else if (dir == "backward") { 
    digitalWrite(IN2, HIGH); 
    digitalWrite(IN4, HIGH); 
  }
  else if (dir == "left") { 
    digitalWrite(IN1, HIGH); 
    digitalWrite(IN4, HIGH); 
  }
  else if (dir == "right") { 
    digitalWrite(IN2, HIGH); 
    digitalWrite(IN3, HIGH); 
  }
  else if (dir == "forward_left") { 
    digitalWrite(IN1, HIGH); 
  }
  else if (dir == "forward_right") { 
    digitalWrite(IN3, HIGH); 
  }
  else if (dir == "backward_left") { 
    digitalWrite(IN2, HIGH); 
  }
  else if (dir == "backward_right") { 
    digitalWrite(IN4, HIGH); 
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
    .mck_io_num = I2S_PIN_NO_CHANGE, 
    .bck_io_num = I2S_MIC_SCK,
    .ws_io_num = I2S_MIC_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = I2S_MIC_SD
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
    .mck_io_num = I2S_PIN_NO_CHANGE, 
    .bck_io_num = I2S_SPK_BCLK,
    .ws_io_num = I2S_SPK_LRC,
    .data_out_num = I2S_SPK_DOUT,
    .data_in_num = I2S_PIN_NO_CHANGE
  };
  i2s_set_pin(SPK_PORT, &pin_config);
  i2s_start(SPK_PORT);
}

void playTone(int16_t amplitude, int duration_cycles) {
  size_t bytes_written;
  int16_t sample[2] = {amplitude, amplitude}; 
  for (int i = 0; i < duration_cycles; i++) {
    i2s_write(SPK_PORT, &sample, sizeof(sample), &bytes_written, portMAX_DELAY);
    sample[0] = -sample[0]; 
    sample[1] = -sample[1]; 
  }
}

// ==========================================
// FREERTOS BACKGROUND TASKS
// ==========================================
void distanceTask(void * pvParameters) {
  while (true) {
    digitalWrite(TRIG_PIN, LOW); 
    delayMicroseconds(2);
    digitalWrite(TRIG_PIN, HIGH); 
    delayMicroseconds(10); 
    digitalWrite(TRIG_PIN, LOW);
    
    long duration = pulseIn(ECHO_PIN, HIGH, 20000); 
    if (duration > 0) {
      float calculatedDist = (duration * 0.0343) / 2.0;
      if (calculatedDist >= 2.0 && calculatedDist <= 400.0) {
        currentDistanceCM = calculatedDist;
      }
    }

    // 🚀 YOUR PREFERRED SIMPLE EVASION LOGIC
    if (currentMovementDir == "forward" && currentDistanceCM < 35.0 && currentDistanceCM > 2.0 && !isEvading) {
      isEvading = true; 
      
      currentEmotion = ANGRY;
      renderFace();
      playTone(18000, 800); 
      
      applyMotors("backward");
      vTaskDelay(150 / portTICK_PERIOD_MS);
      
      applyMotors("right"); 
      vTaskDelay(800 / portTICK_PERIOD_MS);
      
      applyMotors("stop");
      currentEmotion = HAPPY;
      renderFace();
      
      isEvading = false; 
    }

    vTaskDelay(20 / portTICK_PERIOD_MS); 
  }
}

void audioMicTask(void * pvParameters) {
  i2s_mic_install();
  WiFiClient client;
  while (true) {
    if (WiFi.status() == WL_CONNECTED && pythonServerIP != "") {
      if (!client.connected()) {
        client.connect(pythonServerIP.c_str(), pythonServerPort);
      }
      if (client.connected()) {
        size_t bytesIn = 0;
        esp_err_t result = i2s_read(MIC_PORT, &sBuffer, BUFFER_LEN * sizeof(int16_t), &bytesIn, portMAX_DELAY);
        if (result == ESP_OK && bytesIn > 0) {
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
        int availableBytes = client.available();
        if (availableBytes >= 4) {
          int bytesToRead = (availableBytes / 4) * 4; 
          if (bytesToRead > 1024) bytesToRead = 1024; 
          int len = client.read(buf, bytesToRead);
          size_t bytes_written;
          i2s_write(SPK_PORT, buf, len, &bytes_written, portMAX_DELAY);
        } else {
          vTaskDelay(2 / portTICK_PERIOD_MS); 
        }
      }
      client.stop();
      isSpeaking = false;
    }
    vTaskDelay(20 / portTICK_PERIOD_MS); 
  }
}

// ==========================================
// TFT DRAWING ROUTINES (160 WIDTH OPTIMIZED)
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
    tft.setCursor(5, 5); tft.setTextColor(ST7735_WHITE); tft.setTextSize(1); tft.print("JARVIS 4WD ACTIVE");
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
// CLOUD IMAGE DOWNLOADER (BUFFER FIX INCLUDED)
// ==========================================
void fetchAndShowProfile(String filename, String name, String role, int hold_ms) {
  tft.fillScreen(ST7735_BLACK);

  String url = "http://" + dashboardServerAddress + "/static/team/" + filename;
  HTTPClient http;
  http.begin(url);
  int httpCode = http.GET();

  if (httpCode == HTTP_CODE_OK) {
    int totalLength = http.getSize();
    WiFiClient *stream = http.getStreamPtr();

    if (totalLength > 0) {
      uint8_t *jpgBuffer = (uint8_t *)malloc(totalLength);
      if (jpgBuffer != nullptr) {
        int loaded = 0;
        while (http.connected() && (loaded < totalLength)) {
          size_t size = stream->available();
          if (size) {
            int c = stream->readBytes(&jpgBuffer[loaded], ((size > (totalLength - loaded)) ? (totalLength - loaded) : size));
            loaded += c;
          }
          delay(1);
        }
        
        TJpgDec.setJpgScale(2);
        // Centered horizontally: (160 width - 128 image) / 2 = 16
        TJpgDec.drawJpg(16, 0, jpgBuffer, totalLength);
        free(jpgBuffer);
      }
    }
  } else {
    tft.setCursor(15, 55); tft.setTextColor(ST7735_RED); tft.print("IMAGE OFFLINE");
  }
  http.end();

  // Draw a black text banner cleanly over the bottom of the image
  tft.fillRect(16, 108, 128, 20, ST7735_BLACK);
  tft.setCursor(20, 110); tft.setTextColor(ST7735_WHITE); tft.print(name);
  tft.setCursor(20, 118); tft.setTextColor(C_ORANGE); tft.print(role);

  delay(hold_ms);
}

void processTeamDisplaySequence() {
  currentEmotion = TEAM_DISPLAY;
  
  fetchAndShowProfile("meet.jpg", "Meet Bhavsar", "Lead & Firmware", 3000);
  fetchAndShowProfile("bhakti.jpg", "Bhakti Nivgane", "Hardware & Power", 3000);
  fetchAndShowProfile("shreya.jpg", "Shreya Shukla", "AI & Backend Data", 3000);
  fetchAndShowProfile("dhara.jpg", "Dhara Thakkar", "Vision & Tracking", 3000);
  fetchAndShowProfile("janvi.jpg", "Janvi Bhatt", "Audio & Dashboard", 3000);

  currentEmotion = HAPPY;
  renderFace();
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
  } else {
    server.send(400, "text/plain", "Missing IP");
  }
}

void handleEmotion() {
  if (server.hasArg("type")) {
    String state = server.arg("type");
    state.toLowerCase();
    if (state == "thinking") currentEmotion = THINKING; 
    else if (state == "listening") currentEmotion = LISTENING;
    else if (state == "surprise") currentEmotion = SURPRISE; 
    else if (state == "sad") currentEmotion = SAD;
    else if (state == "happy") currentEmotion = HAPPY; 
    else if (state == "angry") currentEmotion = ANGRY;
    else if (state == "sleepy") currentEmotion = SLEEPY; 
    else if (state == "wink") currentEmotion = WINK;
    else if (state == "confused") currentEmotion = CONFUSED;
    renderFace(); 
    server.send(200, "text/plain", "OK");
  } else {
    server.send(400, "text/plain", "Missing type");
  }
}

void handleTeamDisplay() {
  if (server.hasArg("server")) {
    dashboardServerAddress = server.arg("server");
  }
  server.send(200, "text/plain", "Downloading profiles from cloud...");
  processTeamDisplaySequence();
}

void handleShowMember() {
  if (server.hasArg("server")) dashboardServerAddress = server.arg("server");
  String name = server.hasArg("name") ? server.arg("name") : "Member";
  String role = server.hasArg("role") ? server.arg("role") : "Contributor";
  String file = server.hasArg("file") ? server.arg("file") : (name + ".jpg");

  server.send(200, "text/plain", "Showing member: " + name);
  
  currentEmotion = TEAM_DISPLAY;
  fetchAndShowProfile(file, name, role, 4000);
  currentEmotion = HAPPY;
  renderFace();
}

void handleTalk() {
  if (server.hasArg("state")) {
    isSpeaking = (server.arg("state") == "on");
    if (!isSpeaking) {
      tft.fillRect(65, 70, 30, 20, ST7735_BLACK);
      renderFace();
    }
    server.send(200, "text/plain", "OK");
  } else {
    server.send(400, "text/plain", "Missing state");
  }
}

void handleEyes() {
  if (server.hasArg("r") && server.hasArg("g") && server.hasArg("b")) {
    currentEyeColor = tft.color565(server.arg("r").toInt(), server.arg("g").toInt(), server.arg("b").toInt());
    renderFace();
    server.send(200, "text/plain", "OK");
  } else {
    server.send(400, "text/plain", "Missing RGB");
  }
}

void handleMove() {
  if (isEvading) {
    server.send(503, "text/plain", "BUSY: Evasion In Progress");
    return;
  }

  if (server.hasArg("dir")) {
    String dir = server.arg("dir");
    dir.toLowerCase();
    applyMotors(dir);
    server.send(200, "text/plain", "OK: Moved " + dir);
  } else {
    server.send(400, "text/plain", "Error: Missing dir parameter");
  }
}

void handleDistance() {
  server.send(200, "text/plain", String(currentDistanceCM, 1));
}

void handleBeep() {
  playTone(15000, 2000);
  server.send(200, "text/plain", "Beeped");
}

// ==========================================
// SETUP & MAIN LOOP
// ==========================================
void setup() {
  Serial.begin(115200);

  // Status Indicator
  pinMode(STATUS_LED, OUTPUT); 
  digitalWrite(STATUS_LED, HIGH);

  // Distance Sensor
  pinMode(TRIG_PIN, OUTPUT); 
  pinMode(ECHO_PIN, INPUT);

  // Audio System
  i2s_speaker_install();

  // SPI Setup & 160x128 Initialization
  SPI.begin(18, -1, 23, -1);
  tft.initR(INITR_BLACKTAB);
  tft.setRotation(1);
  tft.fillScreen(ST7735_BLACK);

  // Motor Driver Pins
  pinMode(IN1, OUTPUT); digitalWrite(IN1, LOW);
  pinMode(IN2, OUTPUT); digitalWrite(IN2, LOW);
  pinMode(IN3, OUTPUT); digitalWrite(IN3, LOW);
  pinMode(IN4, OUTPUT); digitalWrite(IN4, LOW);

  // Boot Splash Animation
  tft.setCursor(15, 35); tft.setTextColor(ST7735_CYAN); tft.setTextSize(1); tft.print("JARVIS 4WD PRO");
  tft.setCursor(22, 55); tft.setTextColor(ST7735_WHITE); tft.setTextSize(1); tft.print("SYSTEM INITIALIZING");
  tft.drawRect(20, 75, 120, 8, ST7735_BLUE);

  for (int i = 0; i <= 116; i += 20) {
    tft.fillRect(22, 77, i, 4, ST7735_CYAN);
    if (i == 40) playTone(10000, 1000);
    delay(180);
  }

  // Network Configuration
  WiFiManager wifiManager;
  wifiManager.autoConnect("JARVIS_Setup");

  if (MDNS.begin("jarvis")) {
    Serial.println("mDNS responder started: http://jarvis.local");
  }

  // REST API Endpoints
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

  // Background Multitasking Tasks
  xTaskCreatePinnedToCore(audioMicTask, "AudioTask", 10000, NULL, 1, NULL, 0);
  xTaskCreatePinnedToCore(audioPlaybackTask, "AudioPlayback", 10000, NULL, 1, NULL, 0);
  xTaskCreatePinnedToCore(distanceTask, "DistTask", 4096, NULL, 1, NULL, 0);
}

void loop() {
  server.handleClient();
  updateAnimations();
  delay(2);
}