/*
  ESP32 -> Raspberry Pi over Bluetooth Low Energy (BLE)
  Sends MQ135 gas readings + battery voltage every few seconds.

  Wiring (classic ESP32 DevKit):
    MQ135 AO        -> GPIO34   (see the 5V WARNING below!)
    Battery divider -> GPIO35   (Battery+ -> 32k -> GPIO35 -> 7.5k -> GND)
    Grounds of battery, MQ135 and ESP32 must be connected together.

  5V WARNING: an MQ135 module powered from 5V can output up to ~5V on AO, but ESP32
  ADC pins tolerate 3.3V max. Put a divider on AO (e.g. 10k from AO to the pin, 15k from
  the pin to GND) and set MQ_AO_RATIO below to (Rtop + Rbottom) / Rbottom = 1.667.

  Use ADC1 pins only (GPIO32-39). ADC2 pins do not work while Bluetooth/WiFi is on.

  Board: Tools -> Board -> "ESP32 Dev Module" (esp32 core by Espressif, v2.x or v3.x)
*/

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <math.h>

// ================== SETTINGS YOU MAY CHANGE ==================

const char*    DEVICE_NAME      = "ESP32-AirSensor";   // Pi looks for this name
const uint32_t SEND_INTERVAL_MS = 2000;                // how often to send

// ---- Pins ----
const int MQ135_PIN = 34;
const int BAT_PIN   = 35;

// ---- Battery divider: 32k (top, to Battery+) and 7.5k (bottom, to GND) ----
const float R_TOP     = 32000.0;
const float R_BOTTOM  = 7500.0;
const float DIV_RATIO = (R_TOP + R_BOTTOM) / R_BOTTOM;  // = 5.267
const float BAT_CAL   = 1.000;   // fine-tune: multimeter_voltage / reported_voltage
const float BAT_EMPTY_V = 9.0;   // voltage you call 0%   (set for YOUR battery)
const float BAT_FULL_V  = 12.6;  // voltage you call 100% (set for YOUR battery)

// ---- MQ135 ----
const float MQ_VC       = 5.0;   // voltage the MQ135 module is powered from
const float MQ_RL       = 1.0;   // load resistor on the module, kOhm ("102" = 1k, "103" = 10k)
const float MQ_AO_RATIO = 1.0;   // if you added a divider on AO: (Rtop + Rbottom) / Rbottom, else 1.0
                                 //   e.g. 10k (AO->pin) + 15k (pin->GND) => 25/15 = 1.667
float       MQ_R0       = 10.0;  // kOhm. Replace with the "R0 estimate" printed in clean air (see notes)
const uint32_t MQ_WARMUP_MS = 120000;  // readings unreliable for the first ~2 minutes

// CO2-equivalent curve commonly used for MQ135 (rough estimate only)
const float MQ_PARA  = 116.6020682;
const float MQ_PARB  = 2.769034857;
const float ATMO_CO2 = 420.0;    // outdoor CO2 ppm, used for calibration

// ================== BLE (Nordic UART-style UUIDs) ==================
#define SERVICE_UUID "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define TX_CHAR_UUID "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"   // ESP32 -> Pi (notify)

BLEServer*         server  = nullptr;
BLECharacteristic* txChar  = nullptr;
volatile bool deviceConnected = false;
bool wasConnected = false;

class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* s) override    { deviceConnected = true;  }
  void onDisconnect(BLEServer* s) override { deviceConnected = false; }
};

// Average many readings to reduce ADC noise. analogReadMilliVolts() uses the
// ESP32's factory calibration, so it's more accurate than analogRead().
float readVolts(int pin, int samples = 32) {
  uint32_t sum = 0;
  for (int i = 0; i < samples; i++) {
    sum += analogReadMilliVolts(pin);
    delay(2);
  }
  return (sum / (float)samples) / 1000.0;
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\nESP32 air sensor starting...");

  analogReadResolution(12);

  BLEDevice::init(DEVICE_NAME);
  BLEDevice::setMTU(185);            // allow ~180-byte messages

  server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  BLEService* service = server->createService(SERVICE_UUID);
  txChar = service->createCharacteristic(
      TX_CHAR_UUID,
      BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_READ);
  txChar->addDescriptor(new BLE2902());
  service->start();

  BLEAdvertising* adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(SERVICE_UUID);
  adv->setScanResponse(true);
  BLEDevice::startAdvertising();

  Serial.printf("Advertising as \"%s\"\n", DEVICE_NAME);
}

void loop() {
  static uint32_t lastSend = 0;

  // Restart advertising after the Pi disconnects so it can reconnect
  if (!deviceConnected && wasConnected) {
    delay(300);
    BLEDevice::startAdvertising();
    Serial.println("Pi disconnected - advertising again");
    wasConnected = false;
  }
  if (deviceConnected && !wasConnected) {
    Serial.println("Pi connected");
    wasConnected = true;
  }

  if (millis() - lastSend < SEND_INTERVAL_MS) { delay(10); return; }
  lastSend = millis();

  // ---- Battery ----
  float batPinV = readVolts(BAT_PIN);
  float batV    = batPinV * DIV_RATIO * BAT_CAL;
  int   batPct  = (int)constrain((batV - BAT_EMPTY_V) / (BAT_FULL_V - BAT_EMPTY_V) * 100.0, 0.0, 100.0);

  // ---- MQ135 ----
  float aoV = readVolts(MQ135_PIN) * MQ_AO_RATIO;           // sensor output voltage
  float rs  = (aoV > 0.01) ? MQ_RL * (MQ_VC - aoV) / aoV : -1;  // sensor resistance, kOhm
  float ppm = (rs > 0) ? MQ_PARA * pow(rs / MQ_R0, -MQ_PARB) : -1;
  float r0Estimate = (rs > 0) ? rs * pow(ATMO_CO2 / MQ_PARA, 1.0 / MQ_PARB) : -1;
  int   warm = millis() > MQ_WARMUP_MS ? 1 : 0;

  // ---- Build message (compact JSON) ----
  char msg[180];
  int len = snprintf(msg, sizeof(msg),
      "{\"mq_v\":%.3f,\"rs\":%.2f,\"ppm\":%.0f,\"bat_v\":%.2f,\"bat_pct\":%d,\"warm\":%d,\"up\":%lu}",
      aoV, rs, ppm, batV, batPct, warm, (unsigned long)(millis() / 1000));

  Serial.println(msg);
  Serial.printf("   (battery pin %.3f V | MQ135 R0 estimate for clean air: %.2f kOhm)\n", batPinV, r0Estimate);

  if (deviceConnected) {
    txChar->setValue((uint8_t*)msg, len);
    txChar->notify();
  }
}
