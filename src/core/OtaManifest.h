#pragma once
// OTA manifest: strict key=value parsing.
//   build=<uint32 nonzero>
//   md5=<32 lowercase hex chars>   (optional)
// Update iff manifest.build > runningBuild. Pure logic.
#include <cstdint>
#include <string>

namespace spectra {

struct OtaManifest {
  uint32_t build = 0;
  std::string md5;  // empty when absent
  bool hasMd5 = false;
};

// Returns true only if the manifest is fully valid.
bool parseOtaManifest(const std::string& text, OtaManifest& out);

bool shouldUpdate(uint32_t runningBuild, const OtaManifest& manifest);

bool validMd5(const std::string& md5);

}  // namespace spectra
