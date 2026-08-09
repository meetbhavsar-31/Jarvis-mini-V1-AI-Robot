#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>
#include "img_converters.h" 
#include <WiFiManager.h>
#include <ESPmDNS.h> // REQUIRED: mDNS library for ESP32

// ==========================================
// AI-THINKER ESP32-CAM PIN CONFIGURATION
// ==========================================
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

WebServer server(80);

// ==========================================
// STREAM HANDLER 
// ==========================================
void handle_jpg_stream() {
  camera_fb_t * fb = NULL;
  
  String response = "HTTP/1.1 200 OK\r\n";
  response += "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n";
  server.client().write(response.c_str(), response.length());
  
  while (true) {
    fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Camera capture failed");
      break;
    }
    
    size_t _jpg_buf_len = 0;
    uint8_t * _jpg_buf = NULL;
    
    if(fb->format != PIXFORMAT_JPEG){
      bool jpeg_converted = frame2jpg(fb, 40, &_jpg_buf, &_jpg_buf_len);
      esp_camera_fb_return(fb); 
      fb = NULL;
      if(!jpeg_converted){
        Serial.println("JPEG compression failed");
        break;
      }
    } else {
      _jpg_buf_len = fb->len;
      _jpg_buf = fb->buf;
    }
    
    String header = "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + String(_jpg_buf_len) + "\r\n\r\n";
    server.client().write(header.c_str(), header.length());
    server.client().write((const char *)_jpg_buf, _jpg_buf_len);
    server.client().write("\r\n", 2);
    
    if(fb){
      esp_camera_fb_return(fb); 
    } else if(_jpg_buf){
      free(_jpg_buf); 
    }
  }
}

// ==========================================
// SETUP & LOOP
// ==========================================
void setup() {
  Serial.begin(115200);
  delay(100);
  
  // 1. Initialize Camera
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_RGB565; 
  
  if(psramFound()){
    config.frame_size = FRAMESIZE_QVGA; 
    config.jpeg_quality = 10;          
    config.fb_count = 1;              
  } else {
    config.frame_size = FRAMESIZE_QQVGA;
    config.jpeg_quality = 12;
    config.fb_count = 1;
  }
  
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x", err);
    return;
  }

  // 2. WiFiManager AutoConnect
  WiFiManager wifiManager;
  Serial.println("Starting WiFiManager AP...");
  bool res = wifiManager.autoConnect("JARVIS_Vision_Setup"); 
  if(!res) {
    Serial.println("Failed to connect");
    ESP.restart();
  } 
  Serial.println("\nWiFi connected!");

  // 3. Start mDNS Responder for JARVIS-VISION
  if (MDNS.begin("jarvis-vision")) {
    Serial.println("MDNS responder started! Stream at http://jarvis-vision.local/stream");
  }
  
  // 4. Start Web Server
  server.on("/", HTTP_GET, [](){
    server.send(200, "text/html", "<h1>JARVIS Vision System</h1><p><a href='/stream'>View Live Stream</a></p>");
  });
  server.on("/stream", HTTP_GET, handle_jpg_stream);
  server.begin();
}

void loop() {
  server.handleClient();
  // Note: ESP32 mDNS handles updates automatically in the background, no MDNS.update() needed here.
}