/*
 * ThermaSand v1.3 - High-Temp Data Logger
 * Focus: Real-time acquisition for 220V Manual Systems
 * PSI is set manually via the Streamlit admin dashboard.
 */

#include <max6675.h>

// MAX6675 Pin Configuration
int thermoSO = 19;
int thermoCS = 5;
int thermoCLK = 18;

MAX6675 thermocouple(thermoCLK, thermoCS, thermoSO);

void setup() {
  Serial.begin(115200);
  Serial.println("SYSTEM_START");
  delay(500); // Allow sensor to stabilize
}

void loop() {
  // Read Temperature from MAX6675 thermocouple
  float temperature = thermocouple.readCelsius();

  // Safety check: sensor not ready or disconnected
  if (temperature < 0 || isnan(temperature)) {
    Serial.println("ERROR:SENSOR_NOT_READY");
    delay(500);
    return;
  }

  // Format: T:[temp]
  // Parsed by the Streamlit dashboard (dashboard.py)
  // PSI is no longer sent from the ESP32; it is set manually by admin.
  Serial.print("T:");
  Serial.println(temperature);

  delay(500); // Data frequency: 2Hz
}