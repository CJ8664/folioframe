#pragma once
// OTA: manifest check + MD5-verified streaming flash into the inactive
// partition. Battery gate enforced here. Manifest policy in core/.
#include <Arduino.h>

#include "../core/OtaManifest.h"
#include "../hal/Board.h"

class OtaManager {
 public:
  explicit OtaManager(Board* board) : board_(board) {}

  // Returns true if an update was installed (caller should reboot).
  // currentBuild: this firmware's build number (FW_BUILD).
  bool checkAndInstall(const char* versionUrl, const char* firmwareUrl,
                       uint32_t currentBuild);

  String lastError() const { return lastError_; }

 private:
  Board* board_;
  String lastError_;
};
