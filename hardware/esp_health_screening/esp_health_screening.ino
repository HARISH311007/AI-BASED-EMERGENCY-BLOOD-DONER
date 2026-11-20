/*
  ========================================================================
  AI Blood Donor Finder & Health Screening System - ESP32 Firmware (v4-fix)
  Board: ESP32 Dev Kit V1

  Wiring:
  1. MAX30102 pulse oximeter  : VCC->3V3, GND->GND, SDA->GPIO21, SCL->GPIO22 (0x57)
  2. 1.3" OLED (SH1106)       : VCC->3V3, GND->GND, SDA->GPIO21, SCL->GPIO22 (0x3C)
  3. DS18B20 temperature      : VCC->3V3, GND->GND, DATA->GPIO4 + 4.7k pull-up DATA->3V3

  Libraries (Arduino IDE -> Tools -> Manage Libraries):
  1. "U8g2" by olikraus
  2. "SparkFun MAX3010x Pulse and Proximity Sensor Library"
  3. "DallasTemperature" by Miles Burton
  4. "OneWire" by Jim Studt / Paul Stoffregen

  v4 Fixes:
  - DS18B20: Set 10-bit resolution (187ms conversion) so reads complete faster.
             Allow first "85.0" power-on reading to pass through gracefully.
             Increase fail tolerance before marking sensor dead.
  - MAX30102: Reduced sample rate to 100 sps to prevent FIFO overflow.
              Lowered I2C clock to 100kHz for stable shared-bus operation with OLED.
              Removed spo2_algorithm.h dependency (uses simple R/IR ratio method).
              Added explicit FIFO clear on init to prevent stale data.
  - OLED: Reduced refresh rate to every 2s to avoid I2C bus contention.
  - General: Added yield() calls, watchdog-safe timing.
  ========================================================================
*/

#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <U8g2lib.h>
#include "MAX30105.h"
#include "heartRate.h"

// ======================== HARDWARE CONFIG ========================
#define ONE_WIRE_BUS 4
#define I2C_SDA_PIN  21
#define I2C_SCL_PIN  22

#define OLED_I2C_ADDRESS 0x3C
#define MAX_I2C_ADDRESS  0x57

// 1 = SH1106 (typical 1.3" module), 0 = SSD1306 (typical 0.96" module)
#define USE_SH1106 1

#if USE_SH1106
  U8G2_SH1106_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);
#else
  U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);
#endif

OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature tempSensors(&oneWire);
MAX30105 particleSensor;

bool oledDetected      = false;
bool maxSensorDetected = false;
bool ds18b20Detected   = false;

// ======================== WIFI ========================
const char* STA_SSID = "YOUR_WIFI_NAME";
const char* STA_PASS = "YOUR_WIFI_PASSWORD";

const char* AP_SSID  = "ESP_Health_Sensor";
const char* AP_PASS  = "12345678";

WebServer server(80);

// ======================== VITALS STATE ========================
float bodyTemperature = 0.0;
bool  tempValid       = false;
byte  tempFailCount   = 0;
bool  tempRequested   = false;       // track if a conversion is in progress
unsigned long lastTempRequest = 0;

int  heartRate     = 0;
int  spo2Level     = 0;
bool fingerPresent = false;
long irValue       = 0;

int systolicBP  = 120;   // placeholder (not measured by MAX30102)
int diastolicBP = 80;

const long FINGER_THRESHOLD = 7500;  // lowered: some MAX30102 modules report lower IR

// Heart rate averaging
unsigned long lastBeatTime = 0;
const byte RATE_SIZE = 4;
byte rates[RATE_SIZE];
byte rateSpot  = 0;
byte rateCount = 0;

// SpO2 via simple Red/IR ratio (no external algorithm dependency)
float spo2Sum    = 0;
int   spo2Samples = 0;

unsigned long lastSampleMs = 0;
unsigned long lastReadTime = 0;
unsigned long lastOledTime = 0;
bool staIpReported = false;

// DS18B20 first-boot flag: first read is always 85.0°C (power-on reset), skip it
bool ds18b20FirstRead = true;

// ======================== HELPERS ========================
bool i2cDevicePresent(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

uint8_t readRegister8(uint8_t addr, uint8_t reg) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.endTransmission(false);
  Wire.requestFrom(addr, (uint8_t)1);
  return Wire.available() ? Wire.read() : 0xFF;
}

void scanI2C() {
  Serial.println("I2C scan (SDA=21, SCL=22):");
  byte found = 0;
  for (uint8_t a = 1; a < 127; a++) {
    if (i2cDevicePresent(a)) {
      Serial.print("  found 0x"); Serial.print(a, HEX);
      if (a == 0x3C || a == 0x3D) Serial.print("  (OLED)");
      if (a == 0x57)               Serial.print("  (MAX30102/30100)");
      Serial.println();
      found++;
    }
  }
  if (!found) Serial.println("  NOTHING found -> check SDA/SCL/3V3/GND wiring");
}

String currentIP() {
  return (WiFi.status() == WL_CONNECTED) ? WiFi.localIP().toString()
                                         : WiFi.softAPIP().toString();
}

void setCORSHeaders() {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
}

// ======================== SENSOR INIT ========================
bool initOLED() {
  if (!i2cDevicePresent(OLED_I2C_ADDRESS)) return false;
  u8g2.begin();
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(0, 12, "MEDIPULSE AI SYSTEM");
  u8g2.drawStr(0, 28, "Starting sensors...");
  u8g2.sendBuffer();
  return true;
}

void resetMeasurement() {
  fingerPresent = false;
  heartRate = 0;
  spo2Level = 0;
  rateSpot = 0;
  rateCount = 0;
  spo2Sum = 0;
  spo2Samples = 0;
}

bool initMAX(bool verbose) {
  if (!i2cDevicePresent(MAX_I2C_ADDRESS)) {
    if (verbose) Serial.println("MAX30102 not found at 0x57 (check SDA/SCL/VIN/GND).");
    return false;
  }

  // Use I2C_SPEED_STANDARD (100kHz) for reliable shared-bus with OLED
  if (!particleSensor.begin(Wire, I2C_SPEED_STANDARD)) {
    if (verbose) {
      uint8_t id = readRegister8(MAX_I2C_ADDRESS, 0xFF);
      Serial.print("Device at 0x57 but library rejected it. Part ID = 0x");
      Serial.print(id, HEX);
      if (id == 0x11) Serial.println("  -> MAX30100 detected. Use MAX30100 library instead.");
      else            Serial.println("  (MAX30102 should report 0x15)");
    }
    return false;
  }

  // Configuration: ledBrightness, sampleAvg, ledMode, sampleRate, pulseWidth, adcRange
  //   ledBrightness = 0x1F (moderate, not too bright to saturate)
  //   sampleAvg     = 4   (averages 4 samples internally -> smoother)
  //   ledMode       = 2   (Red + IR for SpO2)
  //   sampleRate    = 100  (100 sps effective = 25 Hz after 4x avg -> manageable)
  //   pulseWidth    = 411  (longest pulse for best SNR)
  //   adcRange      = 4096 (full range)
  particleSensor.setup(0x1F, 4, 2, 100, 411, 4096);

  // Clear any stale FIFO data from previous run
  particleSensor.clearFIFO();

  resetMeasurement();
  lastSampleMs = millis();
  lastBeatTime = millis();

  if (verbose) {
    uint8_t id = readRegister8(MAX_I2C_ADDRESS, 0xFF);
    Serial.print("MAX30102 initialized at 0x57. Part ID = 0x");
    Serial.println(id, HEX);
  }
  return true;
}

bool initDS18B20(bool verbose) {
  tempSensors.begin();

  int deviceCount = tempSensors.getDeviceCount();
  if (verbose) {
    Serial.print("DS18B20 scan on GPIO4: ");
    Serial.print(deviceCount);
    Serial.println(" device(s) found.");
  }

  if (deviceCount == 0) {
    if (verbose) Serial.println("DS18B20 not found. Check: DATA->GPIO4, 4.7k pull-up to 3V3, VCC->3V3, GND->GND.");
    return false;
  }

  // Use 10-bit resolution: 187.5ms conversion (vs 750ms for 12-bit default)
  // This prevents blocking and FIFO overflow on the MAX30102
  tempSensors.setResolution(10);
  tempSensors.setWaitForConversion(false);  // non-blocking reads
  tempSensors.requestTemperatures();
  lastTempRequest = millis();
  tempRequested = true;
  tempFailCount = 0;
  ds18b20FirstRead = true;

  if (verbose) {
    DeviceAddress addr;
    if (tempSensors.getAddress(addr, 0)) {
      Serial.print("DS18B20 address: ");
      for (int i = 0; i < 8; i++) {
        if (addr[i] < 16) Serial.print("0");
        Serial.print(addr[i], HEX);
      }
      Serial.println();
    }
    Serial.println("DS18B20 initialized (10-bit, non-blocking).");
  }
  return true;
}

// ======================== TEMPERATURE READING ========================
void readTemperatureSensor() {
  if (!ds18b20Detected) { tempValid = false; return; }

  // Wait at least 250ms for 10-bit conversion to complete
  if (!tempRequested) {
    tempSensors.requestTemperatures();
    lastTempRequest = millis();
    tempRequested = true;
    return;
  }

  if (millis() - lastTempRequest < 250) return;  // conversion not ready yet

  float t = tempSensors.getTempCByIndex(0);
  tempRequested = false;  // mark: ready for next request

  // First read after power-on is always 85.0°C — ignore it
  if (ds18b20FirstRead) {
    ds18b20FirstRead = false;
    if (t == 85.0) {
      Serial.println("DS18B20: Skipping power-on reset value (85.0°C).");
      return;  // will request again on next cycle
    }
  }

  // DEVICE_DISCONNECTED_C is -127.0
  if (t == DEVICE_DISCONNECTED_C || t == -127.0) {
    tempFailCount++;
    Serial.print("DS18B20 read failed (disconnected). Fail count: ");
    Serial.println(tempFailCount);
    if (tempFailCount >= 5) {
      tempValid = false;
      bodyTemperature = 0.0;
      ds18b20Detected = false;
      Serial.println("DS18B20 marked as disconnected. Will retry in 5s.");
    }
    return;
  }

  // Valid reading range check
  if (t > -40.0 && t < 125.0) {
    bodyTemperature = t;
    tempValid = true;
    tempFailCount = 0;
  } else {
    tempFailCount++;
    Serial.print("DS18B20 out of range: "); Serial.print(t); Serial.println("°C");
  }
}

// ======================== PULSE OXIMETER READING ========================
void updatePulseOximeter() {
  if (!maxSensorDetected) return;

  particleSensor.check();  // read new samples from FIFO

  while (particleSensor.available()) {
    uint32_t red = particleSensor.getFIFORed();
    uint32_t ir  = particleSensor.getFIFOIR();
    particleSensor.nextSample();
    lastSampleMs = millis();
    irValue = (long)ir;

    // Finger detection: IR value > threshold means finger is placed
    if ((long)ir < FINGER_THRESHOLD) {
      if (fingerPresent || heartRate || spo2Level) {
        resetMeasurement();
      }
      continue;
    }
    fingerPresent = true;

    // ---- Heart Rate via beat detection ----
    if (checkForBeat(ir)) {
      unsigned long now = millis();
      unsigned long delta = now - lastBeatTime;
      lastBeatTime = now;

      if (delta > 300 && delta < 1500) {  // 40-200 BPM range
        float bpm = 60000.0 / (float)delta;
        rates[rateSpot++] = (byte)bpm;
        rateSpot %= RATE_SIZE;
        if (rateCount < RATE_SIZE) rateCount++;

        int sum = 0;
        for (byte i = 0; i < rateCount; i++) sum += rates[i];
        heartRate = sum / rateCount;
      }
    }

    // ---- SpO2 via Red/IR ratio ----
    // Simple ratio-of-ratios approximation (no external algorithm needed)
    if (red > 1000 && ir > 1000) {
      float ratio = (float)red / (float)ir;
      float spo2Estimate = 110.0 - (25.0 * ratio);

      spo2Sum += spo2Estimate;
      spo2Samples++;

      // Average over 25 samples for stable reading
      if (spo2Samples >= 25) {
        int avgSpo2 = (int)(spo2Sum / spo2Samples);
        if (avgSpo2 >= 85 && avgSpo2 <= 100) {
          spo2Level = avgSpo2;
        }
        spo2Sum = 0;
        spo2Samples = 0;
      }
    }
  }

  // If sensor stops sending data for 5 seconds, mark as disconnected
  if (millis() - lastSampleMs > 5000) {
    Serial.println("MAX30102 stopped responding - marking disconnected.");
    maxSensorDetected = false;
    resetMeasurement();
  }
}

// ======================== RETRY MISSING HARDWARE ========================
void retryMissingHardware() {
  static unsigned long last = 0;
  if (millis() - last < 5000) return;
  last = millis();

  if (!oledDetected) {
    oledDetected = initOLED();
    if (oledDetected) Serial.println("OLED recovered!");
  }
  if (!maxSensorDetected) {
    maxSensorDetected = initMAX(false);
    if (maxSensorDetected) Serial.println("MAX30102 recovered!");
  }
  if (!ds18b20Detected) {
    ds18b20Detected = initDS18B20(false);
    if (ds18b20Detected) Serial.println("DS18B20 recovered!");
  }
}

// ======================== OLED DISPLAY ========================
void updateOLEDDisplay() {
  if (!oledDetected) return;
  char line[28];

  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);

  u8g2.drawStr(0, 9, "MEDIPULSE AI - DONOR");
  u8g2.drawHLine(0, 12, 128);

  // Temperature
  if (tempValid)
    snprintf(line, sizeof(line), "Temp : %.1f C", bodyTemperature);
  else if (ds18b20Detected)
    snprintf(line, sizeof(line), "Temp : reading...");
  else
    snprintf(line, sizeof(line), "Temp : -- (no probe)");
  u8g2.drawStr(0, 25, line);

  // Heart Rate
  if (!maxSensorDetected)
    snprintf(line, sizeof(line), "Pulse: -- (no sensor)");
  else if (fingerPresent && heartRate > 0)
    snprintf(line, sizeof(line), "Pulse: %d BPM", heartRate);
  else if (fingerPresent)
    snprintf(line, sizeof(line), "Pulse: measuring...");
  else
    snprintf(line, sizeof(line), "Pulse: place finger");
  u8g2.drawStr(0, 37, line);

  // SpO2
  if (!maxSensorDetected)
    snprintf(line, sizeof(line), "SpO2 : -- (no sensor)");
  else if (fingerPresent && spo2Level > 0)
    snprintf(line, sizeof(line), "SpO2 : %d %%", spo2Level);
  else if (fingerPresent)
    snprintf(line, sizeof(line), "SpO2 : measuring...");
  else
    snprintf(line, sizeof(line), "SpO2 : place finger");
  u8g2.drawStr(0, 49, line);

  // Bottom line: IP or instruction
  snprintf(line, sizeof(line), "IP:%s", currentIP().c_str());
  u8g2.drawStr(0, 61, line);

  u8g2.sendBuffer();
}

// ======================== HTTP HANDLERS ========================
String boolStr(bool b) { return b ? "true" : "false"; }

void handleVitals() {
  setCORSHeaders();
  bool hrOk  = fingerPresent && heartRate > 0;
  bool spoOk = fingerPresent && spo2Level > 0;

  String json = "{";
  json += "\"status\":\"OK\",";
  json += "\"device_id\":\"ESP32-DEV-KIT-V1\",";
  json += "\"temperature\":" + String(tempValid ? bodyTemperature : 0.0, 1) + ",";
  json += "\"temp_valid\":" + boolStr(tempValid) + ",";
  json += "\"heart_rate\":" + String(hrOk ? heartRate : 0) + ",";
  json += "\"hr_valid\":" + boolStr(hrOk) + ",";
  json += "\"spo2\":" + String(spoOk ? spo2Level : 0) + ",";
  json += "\"spo2_valid\":" + boolStr(spoOk) + ",";
  json += "\"finger_detected\":" + boolStr(fingerPresent) + ",";
  json += "\"systolic_bp\":" + String(systolicBP) + ",";
  json += "\"diastolic_bp\":" + String(diastolicBP) + ",";
  json += "\"bp_measured\":false,";
  json += "\"sensor_status\":\"" + String(maxSensorDetected ? "MAX30102_CONNECTED" : "STANDBY_READY") + "\",";
  json += "\"sensors\":{\"max30102\":" + boolStr(maxSensorDetected) +
          ",\"ds18b20\":" + boolStr(ds18b20Detected) +
          ",\"oled\":" + boolStr(oledDetected) + "}";
  json += "}";
  server.send(200, "application/json", json);
}

void handleRoot() {
  setCORSHeaders();
  bool hrOk  = fingerPresent && heartRate > 0;
  bool spoOk = fingerPresent && spo2Level > 0;
  bool allOk = maxSensorDetected && ds18b20Detected && oledDetected;

  String html = "<!DOCTYPE html><html><head><meta charset='utf-8'>";
  html += "<meta name='viewport' content='width=device-width, initial-scale=1.0'>";
  html += "<meta http-equiv='refresh' content='2'><title>ESP32 Health Telemetry</title>";
  html += "<style>body{font-family:sans-serif;background:#0B0F19;color:#F8FAFC;text-align:center;padding:24px;}";
  html += ".box{background:#111827;border:1px solid #10B981;border-radius:12px;padding:20px;max-width:380px;margin:auto;}";
  html += "h2{color:#10B981;}";
  html += ".row{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #1F2937;font-size:1.1rem;}";
  html += ".badge{color:#FFF;padding:4px 10px;border-radius:20px;font-size:0.8rem;}";
  html += "</style></head><body><div class='box'><h2>Donor Telemetry</h2>";
  html += String("<span class='badge' style='background:") + (allOk ? "#059669'>ALL SENSORS OK" : "#B45309'>CHECK SENSORS") + "</span><br><br>";
  html += "<div class='row'><span>Temperature:</span><b>" + (tempValid ? String(bodyTemperature, 1) + " &deg;C" : String("--")) + "</b></div>";
  html += "<div class='row'><span>Pulse Rate:</span><b>" + (hrOk ? String(heartRate) + " BPM" : String("--")) + "</b></div>";
  html += "<div class='row'><span>SpO2 Level:</span><b>" + (spoOk ? String(spo2Level) + " %" : String("--")) + "</b></div>";
  html += "<div class='row'><span>Finger:</span><b>" + String(fingerPresent ? "detected" : "place finger") + "</b></div>";
  html += "<p style='font-size:0.8rem;color:#94A3B8;margin-top:16px;'>JSON endpoint: <code>/vitals</code><br>";
  html += "MAX30102: " + String(maxSensorDetected ? "ok" : "missing") +
          " | DS18B20: " + String(ds18b20Detected ? "ok" : "missing") +
          " | OLED: " + String(oledDetected ? "ok" : "missing") + "</p>";
  html += "</div></body></html>";
  server.send(200, "text/html", html);
}

void handleOptions() {
  setCORSHeaders();
  server.send(204);
}

// ======================== SETUP ========================
void setup() {
  Serial.begin(115200);
  delay(1500);  // give USB serial time to connect
  Serial.println("\n========================================================");
  Serial.println("  AI BLOOD DONOR FINDER - ESP32 HEALTH TELEMETRY v4-fix");
  Serial.println("========================================================");

  // Initialize I2C at 100kHz (STABLE for shared OLED + MAX30102 bus)
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(100000);   // 100kHz — DO NOT use 400kHz with shared OLED bus
  delay(100);

  scanI2C();

  // Init sensors in order: OLED first (visual feedback), then MAX, then DS18B20
  oledDetected = initOLED();
  Serial.println(oledDetected ? "OLED: OK at 0x3C" : "OLED: not found (will retry)");

  delay(100);  // brief pause between I2C device inits

  maxSensorDetected = initMAX(true);
  Serial.println(maxSensorDetected ? "MAX30102: OK" : "MAX30102: not working (will retry every 5s)");

  delay(100);

  ds18b20Detected = initDS18B20(true);
  Serial.println(ds18b20Detected ? "DS18B20: OK" : "DS18B20: not found (will retry every 5s)");

  // WiFi
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(AP_SSID, AP_PASS);
  Serial.print("SoftAP SSID: "); Serial.print(AP_SSID);
  Serial.print("  IP: "); Serial.println(WiFi.softAPIP());
  if (String(STA_SSID) != "YOUR_WIFI_NAME") {
    WiFi.begin(STA_SSID, STA_PASS);
    Serial.print("Connecting to: "); Serial.println(STA_SSID);
  }

  // HTTP
  server.on("/", HTTP_GET, handleRoot);
  server.on("/vitals", HTTP_GET, handleVitals);
  server.on("/vitals", HTTP_OPTIONS, handleOptions);
  server.begin();
  Serial.println("REST API server started on port 80.");
  Serial.println("========================================================\n");

  updateOLEDDisplay();
}

// ======================== LOOP ========================
void loop() {
  server.handleClient();

  // Poll MAX30102 as fast as possible — beat detection needs rapid sampling
  updatePulseOximeter();

  // Non-blocking temperature read
  readTemperatureSensor();

  // Retry disconnected sensors every 5s
  retryMissingHardware();

  // Report Wi-Fi station IP once connected
  if (!staIpReported && WiFi.status() == WL_CONNECTED) {
    staIpReported = true;
    Serial.print("Wi-Fi connected. Station IP: "); Serial.println(WiFi.localIP());
    updateOLEDDisplay();
  }

  // Update OLED every 2 seconds (less frequent = less I2C contention)
  if (millis() - lastOledTime > 2000) {
    lastOledTime = millis();
    updateOLEDDisplay();
  }

  // Serial debug log every 2 seconds
  if (millis() - lastReadTime > 2000) {
    lastReadTime = millis();

    Serial.print("Temp: ");
    if (tempValid) { Serial.print(bodyTemperature, 1); Serial.print("C"); }
    else Serial.print("--");

    Serial.print(" | IR: "); Serial.print(irValue);
    Serial.print(" | finger: "); Serial.print(fingerPresent ? "YES" : "no");
    Serial.print(" | HR: "); Serial.print(heartRate > 0 ? String(heartRate) : String("--"));
    Serial.print(" | SpO2: "); Serial.print(spo2Level > 0 ? String(spo2Level) : String("--"));
    Serial.print(" | hw: MAX="); Serial.print(maxSensorDetected ? "ok" : "MISS");
    Serial.print(" DS="); Serial.print(ds18b20Detected ? "ok" : "MISS");
    Serial.print(" OLED="); Serial.println(oledDetected ? "ok" : "MISS");
  }

  yield();  // prevent watchdog reset
}
