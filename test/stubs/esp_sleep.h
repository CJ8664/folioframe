#pragma once
#include <stdint.h>
#define ESP_EXT1_WAKEUP_ANY_LOW 0
typedef enum {
  ESP_SLEEP_WAKEUP_UNDEFINED,
  ESP_SLEEP_WAKEUP_TIMER,
  ESP_SLEEP_WAKEUP_EXT1
} esp_sleep_wakeup_cause_t;
void esp_sleep_enable_timer_wakeup(uint64_t us);
void esp_sleep_enable_ext1_wakeup(uint64_t mask, int mode);
void esp_deep_sleep_start();
esp_sleep_wakeup_cause_t esp_sleep_get_wakeup_cause();
uint64_t esp_sleep_get_ext1_wakeup_status();
