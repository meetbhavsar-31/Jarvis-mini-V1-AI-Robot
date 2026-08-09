#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <Wire.h>
#include <Adafruit_PCF8574.h>
#include <WiFiManager.h>
#include <ESP8266mDNS.h> 

// --- ST7735 DISPLAY LIBRARIES ---
#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <SPI.h>

ESP8266WebServer server(80);
Adafruit_PCF8574 pcf;

// ==========================================
// PIN DEFINITIONS 
// ==========================================
#define SDA_PIN 4 // D2
#define SCL_PIN 5 // D1

// PCF8574 Expander Pins (P0 to P7)
#define IN1      0 // Left Motor Dir 1
#define IN2      1 // Left Motor Dir 2
#define IN3      2 // Right Motor Dir 1
#define IN4      3 // Right Motor Dir 2

// --- DISPLAY PIN DEFINITIONS ---
#define TFT_CS   16 // D0
#define TFT_RST  0  // D3
#define TFT_DC   2  // D4

// --- Create the display object ---
Adafruit_ST7735 tft = Adafruit_ST7735(TFT_CS, TFT_DC, TFT_RST);

// Global state for current eye color
uint16_t currentEyeColor = ST7735_CYAN;

// ==========================================
// JARVIS FACE DRAWING LOGIC
// ==========================================
void drawJarvisFace(uint16_t color, bool blinking, bool speaking, bool mouthOpen) {
  tft.fillScreen(ST7735_BLACK); // Clear screen

  if (blinking) {
    // Blinking Eyes (Horizontal Lines)
    tft.drawFastHLine(20, 40, 45, color);
    tft.drawFastHLine(20, 41, 45, color); // thicker line
    tft.drawFastHLine(95, 40, 45, color);
    tft.drawFastHLine(95, 41, 45, color);
  } else {
    // Left Eye (Angled Quadrilateral made of 2 Triangles)
    tft.fillTriangle(25, 20,  70, 25,  60, 55, color);
    tft.fillTriangle(25, 20,  60, 55,  25, 48, color);

    // Right Eye (Angled Quadrilateral made of 2 Triangles)
    tft.fillTriangle(90, 25, 135, 20, 135, 48, color);
    tft.fillTriangle(90, 25, 135, 48, 100, 55, color);
  }

  // Mouth Section
  if (speaking) {
    if (mouthOpen) {
      // Audio Equalizer bars when talking
      tft.fillRect(65, 75, 7, 15, color);
      tft.fillRect(76, 70, 8, 25, color);
      tft.fillRect(88, 75, 7, 15, color);
    } else {
      // Small mouth bars
      tft.fillRect(65, 80, 7, 5, color);
      tft.fillRect(76, 78, 8, 9, color);
      tft.fillRect(88, 80, 7, 5, color);
    }
  } else {
    // Resting Mouth Line
    tft.fillRect(65, 82, 30, 3, color);
  }
}

// ==========================================
// MOTOR CONTROL LOGIC
// ==========================================
void stopMotors() {
  pcf.digitalWrite(IN1, LOW);
  pcf.digitalWrite(IN2, LOW);
  pcf.digitalWrite(IN3, LOW);
  pcf.digitalWrite(IN4, LOW);
}

void moveForward() {
  pcf.digitalWrite(IN1, HIGH);
  pcf.digitalWrite(IN2, LOW);
  pcf.digitalWrite(IN3, HIGH);
  pcf.digitalWrite(IN4, LOW);
}

void moveBackward() {
  pcf.digitalWrite(IN1, LOW);
  pcf.digitalWrite(IN2, HIGH);
  pcf.digitalWrite(IN3, LOW);
  pcf.digitalWrite(IN4, HIGH);
}

void turnLeft() {
  pcf.digitalWrite(IN1, LOW);
  pcf.digitalWrite(IN2, HIGH);
  pcf.digitalWrite(IN3, HIGH);
  pcf.digitalWrite(IN4, LOW);
}

void turnRight() {
  pcf.digitalWrite(IN1, HIGH);
  pcf.digitalWrite(IN2, LOW);
  pcf.digitalWrite(IN3, LOW);
  pcf.digitalWrite(IN4, HIGH);
}

// ==========================================
// WEB SERVER HANDLERS
// ==========================================
void handleMove() {
  if (!server.hasArg("dir")) {
    server.send(400, "text/plain", "Error: Missing 'dir' parameter");
    return;
  }

  String direction = server.arg("dir");
  Serial.print("Received Move Command: ");
  Serial.println(direction);

  if (direction == "forward") {
    moveForward();
    server.send(200, "text/plain", "Moving Forward");
  } else if (direction == "backward") {
    moveBackward();
    server.send(200, "text/plain", "Moving Backward");
  } else if (direction == "left") {
    turnLeft();
    server.send(200, "text/plain", "Turning Left");
  } else if (direction == "right") {
    turnRight();
    server.send(200, "text/plain", "Turning Right");
  } else if (direction == "stop") {
    stopMotors();
    server.send(200, "text/plain", "Stopping Motors");
  } else {
    server.send(400, "text/plain", "Error: Invalid direction");
  }
}

void handleEyes() {
  if (server.hasArg("r") && server.hasArg("g") && server.hasArg("b")) {
    int r = server.arg("r").toInt();
    int g = server.arg("g").toInt();
    int b = server.arg("b").toInt();
    
    Serial.print("Received Eye Color: RGB(");
    Serial.print(r); Serial.print(", ");
    Serial.print(g); Serial.print(", ");
    Serial.print(b); Serial.println(")");
    
    // Convert RGB to 16-bit color for the TFT screen
    currentEyeColor = tft.color565(r, g, b);
    
    // Instantly redraw the face with the new color!
    drawJarvisFace(currentEyeColor, false, false, false);
    
    server.send(200, "text/plain", "Eye color updated");
  } else {
    server.send(400, "text/plain", "Error: Missing RGB parameters");
  }
}

// ==========================================
// SETUP & MAIN LOOP
// ==========================================
void setup() {
  Serial.begin(115200);
  delay(100);

  // Initialize PCF8574
  Wire.begin(SDA_PIN, SCL_PIN);
  Serial.println("\nInitializing PCF8574 Expander...");
  if (!pcf.begin(0x20, &Wire)) {
    Serial.println("ERROR: Could not find PCF8574!");
    while (1) { delay(1000); } 
  }
  
  pcf.pinMode(IN1, OUTPUT);
  pcf.pinMode(IN2, OUTPUT);
  pcf.pinMode(IN3, OUTPUT);
  pcf.pinMode(IN4, OUTPUT);
  stopMotors();

  // --- INITIALIZE THE DISPLAY ---
  Serial.println("Initializing ST7735 Display...");
  tft.initR(INITR_BLACKTAB);   
  tft.setRotation(1); // Set to Landscape mode for 160x128
  
  // Draw the JARVIS face directly on boot!
  drawJarvisFace(currentEyeColor, false, false, false);

  // Initialize WiFiManager
  WiFiManager wifiManager;
  Serial.println("Starting WiFiManager...");
  bool res = wifiManager.autoConnect("JARVIS_Setup"); 

  if(!res) {
    Serial.println("Failed to connect or hit timeout");
    ESP.restart();
  } 

  Serial.println("\nWiFi connected!");
  Serial.print("JARVIS Motor Server IP: ");
  Serial.println(WiFi.localIP());

  // Start mDNS Responder
  if (MDNS.begin("jarvis")) { 
    Serial.println("MDNS responder started! http://jarvis.local");
  }

  // Attach Web Routes matching Python API
  server.on("/move", HTTP_GET, handleMove);
  server.on("/eyes", HTTP_GET, handleEyes);
  
  server.begin();
  Serial.println("HTTP Web Server started.");
}

void loop() {
  MDNS.update(); 
  server.handleClient();
}