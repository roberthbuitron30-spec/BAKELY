/*
 * BAKELY · Firmware de ejemplo para ESP32 (tanque de fermentación)
 * Publica temperatura (DS18B20) y pH (sonda analógica) por MQTT cada 30 s.
 * Tópico: upec/bakely/<DISPOSITIVO>/<variable>   → lo consume `manage.py mqtt_bridge` o Node-RED.
 *
 * Librerías: PubSubClient, OneWire, DallasTemperature
 * Calibre el pH con soluciones buffer 4.0 y 7.0 y ajuste PH_PENDIENTE / PH_OFFSET.
 */
#include <WiFi.h>
#include <PubSubClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>

const char* WIFI_SSID = "PLANTA_UPEC";
const char* WIFI_PASS = "********";
const char* MQTT_HOST = "192.168.1.50";
const char* DISPOSITIVO = "esp32-tq01";   // debe coincidir con Equipo.dispositivo_iot

const int PIN_TEMP = 4;
const int PIN_PH = 34;
const float PH_PENDIENTE = -5.70;
const float PH_OFFSET = 21.34;

WiFiClient wifi;
PubSubClient mqtt(wifi);
OneWire oneWire(PIN_TEMP);
DallasTemperature sensores(&oneWire);

void conectar() {
  while (WiFi.status() != WL_CONNECTED) { WiFi.begin(WIFI_SSID, WIFI_PASS); delay(3000); }
  while (!mqtt.connected()) { mqtt.connect(DISPOSITIVO); if (!mqtt.connected()) delay(2000); }
}

void publicar(const char* variable, float valor, int decimales) {
  char topico[64];
  snprintf(topico, sizeof(topico), "upec/bakely/%s/%s", DISPOSITIVO, variable);
  mqtt.publish(topico, String(valor, decimales).c_str(), true);
}

void setup() {
  sensores.begin();
  mqtt.setServer(MQTT_HOST, 1883);
}

void loop() {
  conectar();
  mqtt.loop();
  static unsigned long ultimo = 0;
  if (millis() - ultimo > 30000) {
    ultimo = millis();
    sensores.requestTemperatures();
    publicar("temperatura", sensores.getTempCByIndex(0), 2);
    float voltaje = analogRead(PIN_PH) * 3.3 / 4095.0;
    publicar("ph", PH_PENDIENTE * voltaje + PH_OFFSET, 2);
  }
}
