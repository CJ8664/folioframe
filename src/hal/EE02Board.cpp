#include "EE02Board.h"

#include <esp_sleep.h>

#include "../../include/board_config.h"
#include "../core/BatteryCurve.h"

// Battery: read BEFORE Wi-Fi comes up to avoid ADC noise (josomm22 lesson),
// 16-sample average, divider enabled only during the read.
static const int kAdcSamples = 16;

BoardInfo EE02Board::info() const {
  return BoardInfo{"EE02", "gdeb0709e01"};
}

void EE02Board::begin() {
  pinMode(EE02_KEY1_PIN, INPUT_PULLUP);
  pinMode(EE02_KEY2_PIN, INPUT_PULLUP);
  pinMode(EE02_KEY3_PIN, INPUT_PULLUP);
  pinMode(EE02_BAT_EN_PIN, OUTPUT);
  digitalWrite(EE02_BAT_EN_PIN, LOW);  // divider off except during reads
  if (EE02_STATUS_LED_PIN >= 0) {
    pinMode(EE02_STATUS_LED_PIN, OUTPUT);
    setLed(false);
  }
}

ButtonId EE02Board::readButtonsRaw() {
  if (digitalRead(EE02_KEY1_PIN) == LOW) return ButtonId::Btn1;
  if (digitalRead(EE02_KEY2_PIN) == LOW) return ButtonId::Btn2;
  if (digitalRead(EE02_KEY3_PIN) == LOW) return ButtonId::Btn3;
  return ButtonId::None;
}

ButtonId EE02Board::pollButton() {
  // Simple debounce: state must be stable across two 20 ms-apart polls.
  ButtonId raw = readButtonsRaw();
  uint32_t now = millis();
  if (raw != lastStable_ && (now - lastPollMs_) > 20) {
    lastPollMs_ = now;
    ButtonId prev = lastStable_;
    lastStable_ = raw;
    // Report press edges only (None -> BtnX), not releases.
    if (prev == ButtonId::None && raw != ButtonId::None) return raw;
  }
  return ButtonId::None;
}

void EE02Board::enableButtonWakeup() {
  const uint64_t mask = (1ULL << EE02_KEY1_PIN) | (1ULL << EE02_KEY2_PIN) |
                        (1ULL << EE02_KEY3_PIN);
  esp_sleep_enable_ext1_wakeup(mask, ESP_EXT1_WAKEUP_ANY_LOW);
}

uint16_t EE02Board::batteryMilliVolts() {
  digitalWrite(EE02_BAT_EN_PIN, HIGH);
  delay(5);  // let the divider settle
  uint32_t sum = 0;
  for (int i = 0; i < kAdcSamples; i++) sum += analogReadMilliVolts(EE02_BAT_ADC_PIN);
  digitalWrite(EE02_BAT_EN_PIN, LOW);
  float pinMv = (float)sum / kAdcSamples;
  float batMv = pinMv * EE02_BAT_DIVIDER_RATIO;
  if (batMv < 2500.0f || batMv > 4400.0f) return 0;  // no battery / invalid
  return (uint16_t)batMv;
}

uint8_t EE02Board::batteryPercent() {
  uint16_t mv = batteryMilliVolts();
  if (mv == 0) return 0;
  if (mv >= 4200) return 100;  // USB powered reads high
  return spectra::batteryPercent(mv);
}

bool EE02Board::usbPowered() {
  // Heuristic: a reading at/above the charger termination voltage while the
  // divider is enabled implies USB power. Proper PMIC detection is a v2 item.
  return batteryMilliVolts() >= 4200;
}

void EE02Board::setPanelPower(bool on) {
  // EE02 panel rail is managed by the Seeed_GFX2 driver init/sleep path;
  // the EN line is owned by the product catalog. Kept as a seam for boards
  // with an explicit load-switch GPIO.
  (void)on;
}

void EE02Board::deepSleep(uint64_t sleepUs) {
  esp_sleep_enable_timer_wakeup(sleepUs);
  esp_deep_sleep_start();
}

WakeCause EE02Board::wakeCause() const {
  switch (esp_sleep_get_wakeup_cause()) {
    case ESP_SLEEP_WAKEUP_TIMER:
      return WakeCause::Timer;
    case ESP_SLEEP_WAKEUP_EXT1:
      return WakeCause::Button;
    case ESP_SLEEP_WAKEUP_UNDEFINED:
      return WakeCause::PowerOn;
    default:
      return WakeCause::Unknown;
  }
}

void EE02Board::setLed(bool on) {
  if (EE02_STATUS_LED_PIN < 0) return;
  bool level = EE02_STATUS_LED_ACTIVE_LOW ? !on : on;
  digitalWrite(EE02_STATUS_LED_PIN, level ? HIGH : LOW);
}

void EE02Board::blinkLed(int times) {
  if (EE02_STATUS_LED_PIN < 0) return;
  for (int i = 0; i < times; i++) {
    setLed(true);
    delay(120);
    setLed(false);
    delay(120);
  }
}

String EE02Board::deviceId() {
  uint64_t mac = ESP.getEfuseMac();
  char buf[12];
  snprintf(buf, sizeof(buf), "SF-%02X%02X%02X", (uint8_t)(mac >> 16),
           (uint8_t)(mac >> 8), (uint8_t)mac);
  return String(buf);
}
