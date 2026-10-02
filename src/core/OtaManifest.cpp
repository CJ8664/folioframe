#include "OtaManifest.h"

namespace spectra {

static std::string trim(const std::string& s) {
  size_t a = s.find_first_not_of(" \t\r\n");
  if (a == std::string::npos) return "";
  size_t b = s.find_last_not_of(" \t\r\n");
  return s.substr(a, b - a + 1);
}

bool validMd5(const std::string& md5) {
  if (md5.size() != 32) return false;
  for (char c : md5) {
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
  }
  return true;
}

bool parseOtaManifest(const std::string& text, OtaManifest& out) {
  OtaManifest m;
  bool sawBuild = false;
  size_t pos = 0;
  while (pos <= text.size()) {
    size_t eol = text.find('\n', pos);
    std::string line = trim(text.substr(pos, eol == std::string::npos
                                                 ? std::string::npos
                                                 : eol - pos));
    if (!line.empty()) {
      size_t eq = line.find('=');
      if (eq == std::string::npos) return false;
      std::string key = trim(line.substr(0, eq));
      std::string val = trim(line.substr(eq + 1));
      if (key == "build") {
        if (val.empty()) return false;
        uint32_t b = 0;
        for (char c : val) {
          if (c < '0' || c > '9') return false;
          b = b * 10 + (uint32_t)(c - '0');
        }
        if (b == 0) return false;  // build 0 disables updates
        m.build = b;
        sawBuild = true;
      } else if (key == "md5") {
        if (!validMd5(val)) return false;
        m.md5 = val;
        m.hasMd5 = true;
      } else {
        return false;  // unknown keys rejected (strict)
      }
    }
    if (eol == std::string::npos) break;
    pos = eol + 1;
  }
  if (!sawBuild) return false;
  out = m;
  return true;
}

bool shouldUpdate(uint32_t runningBuild, const OtaManifest& manifest) {
  return manifest.build > runningBuild;
}

}  // namespace spectra
