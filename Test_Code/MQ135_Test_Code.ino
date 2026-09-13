/*
  MQ135 Simple Serial Reader - Arduino Nano

  Wiring:
    MQ135 VCC  -> Arduino 5V
    MQ135 GND  -> Arduino GND
    MQ135 AOUT -> Arduino A1
*/

const int mq135Pin = A1;

void setup() {
  Serial.begin(9600);
  Serial.println("MQ135 warming up...");
}

void loop() {
  int raw = analogRead(mq135Pin);
  float voltage = raw * (5.0 / 1023.0);

  Serial.print("Raw ADC: ");
  Serial.print(raw);
  Serial.print("   Voltage: ");
  Serial.print(voltage, 3);
  Serial.println(" V");

  delay(1000);
}
