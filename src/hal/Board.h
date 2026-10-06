#pragma once
// Hardware Abstraction: Board.
//
// Porting to a new board = subclass this interface + a pin map.
// No other file may touch GPIOs, ADC, sleep, or the power rail directly.
#include <Arduino.h>

enum class WakeCause { PowerOn, Timer, Button, Unknown };
enum class ButtonId { None, Btn1, Btn2, Btn3 };

struct BoardInfo {
  const char* name;       // "EE02"
  const char* panelKind;  // "gdeb0709e01" (sent as X-Device-Panel)
};

class Board {
 public:
  virtual ~Board() = default;

  virtual BoardInfo info() const = 0;
  virtual void begin() = 0;

  // Poll debounced buttons. Returns the pressed button or ButtonId::None.
  virtual ButtonId pollButton() = 0;
  // True while the given button is currently held down (raw pin read, no
  // debounce). Used for hold-to-confirm gestures (e.g. hold KEY2 to check
  // for a firmware update). Must be callable any time after begin().
  virtual bool buttonHeld(ButtonId id) = 0;
  // millis() timestamp of the last physical press of the button, or 0 if
  // unknown (e.g. the press woke the chip from deep sleep, where GPIO
  // interrupts are inactive). Lets hold gestures measure from the
  // physical press instead of from whenever the firmware polls.
  // Default: unsupported (0).
  virtual uint32_t buttonPressMs(ButtonId id) {
    (void)id;
    return 0;
  }
  // Arm EXT1 wake on any button before deepSleep().
  virtual void enableButtonWakeup() = 0;

  // Battery. Returns 0 when no battery / reading invalid.
  virtual uint16_t batteryMilliVolts() = 0;
  virtual uint8_t batteryPercent() = 0;  // via core::BatteryCurve
  virtual bool usbPowered() = 0;

  // Panel power rail (EN). Cut before deep sleep to save energy.
  virtual void setPanelPower(bool on) = 0;

  // Enter deep sleep; does not return. Timer and (if armed) buttons wake.
  virtual void deepSleep(uint64_t sleepUs) = 0;
  virtual WakeCause wakeCause() const = 0;

  // Status LED. No-op when the board has none.
  virtual void setLed(bool on) = 0;
  virtual void blinkLed(int times) = 0;

  // Stable device id, e.g. "sf-a1b2c3d4e5f6" (MAC-derived, lowercase).
  virtual String deviceId() = 0;
};
