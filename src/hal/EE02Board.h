#pragma once
#include "Board.h"

class EE02Board : public Board {
 public:
  BoardInfo info() const override;
  void begin() override;

  ButtonId pollButton() override;
  void enableButtonWakeup() override;

  uint16_t batteryMilliVolts() override;
  uint8_t batteryPercent() override;
  bool usbPowered() override;

  void setPanelPower(bool on) override;

  void deepSleep(uint64_t sleepUs) override;
  WakeCause wakeCause() const override;

  void setLed(bool on) override;
  void blinkLed(int times) override;

  String deviceId() override;

 private:
  ButtonId readButtonsRaw();
  uint32_t lastPollMs_ = 0;
  ButtonId lastStable_ = ButtonId::None;
};
