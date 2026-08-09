#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <Wire.h>
#include <Adafruit_PCF8574.h>
#include <WiFiManager.h>
#include <ESP8266mDNS.h> // Includes the mDNS library

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
  // Left motor backwards, Right motor forwards
  pcf.digitalWrite(IN1, LOW);
  pcf.digitalWrite(IN2, HIGH);
  pcf.digitalWrite(IN3, HIGH);
  pcf.digitalWrite(IN4, LOW);
}

void turnRight() {
  // Left motor forwards, Right motor backwards
  pcf.digitalWrite(IN1, HIGH);
  pcf.digitalWrite(IN2, LOW);
  pcf.digitalWrite(IN3, LOW);
  pcf.digitalWrite(IN4, HIGH);
}

// ==========================================
// WEB SERVER HANDLERS (Matches Python API)
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
  // This acts as a placeholder so the Python dashboard doesn't get a 404 Error
  // when you click the eye color buttons. You can add NeoPixel logic here later!
  if (server.hasArg("r") && server.hasArg("g") && server.hasArg("b")) {
    String r = server.arg("r");
    String g = server.arg("g");
    String b = server.arg("b");
    
    Serial.print("Received Eye Color Command: RGB(");
    Serial.print(r); Serial.print(", ");
    Serial.print(g); Serial.print(", ");
    Serial.print(b); Serial.println(")");
    
    server.send(200, "text/plain", "Eye color accepted");
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
    Serial.println("ERROR: Could not find PCF8574! Check D1/D2 wiring.");
    while (1) { delay(1000); } 
  }
  
  pcf.pinMode(IN1, OUTPUT);
  pcf.pinMode(IN2, OUTPUT);
  pcf.pinMode(IN3, OUTPUT);
  pcf.pinMode(IN4, OUTPUT);
  stopMotors();

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
    Serial.println("MDNS responder started! You can now use http://jarvis.local");
  }

  // Attach Web Routes matching Python motion_controller.py
  server.on("/move", HTTP_GET, handleMove);
  server.on("/eyes", HTTP_GET, handleEyes);
  
  server.begin();
  Serial.println("HTTP Web Server started.");
}

void loop() {
  MDNS.update(); // Keeps the mDNS broadcast active
  server.handleClient();
}