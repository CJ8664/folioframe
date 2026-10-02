#include "UrlTemplate.h"

namespace spectra {

static std::string replaceAll(std::string s, const std::string& from,
                              const std::string& to) {
  size_t pos = 0;
  while ((pos = s.find(from, pos)) != std::string::npos) {
    s.replace(pos, from.size(), to);
    pos += to.size();
  }
  return s;
}

std::string expandUrlTemplate(const std::string& tpl, const UrlTokens& tok) {
  std::string out = tpl;
  out = replaceAll(out, "{seed}", std::to_string(tok.seed));
  out = replaceAll(out, "{width}", std::to_string(tok.width));
  out = replaceAll(out, "{height}", std::to_string(tok.height));
  return out;
}

bool validImageUrl(const std::string& url) {
  if (url.empty() || url.size() > 512) return false;
  return url.rfind("http://", 0) == 0 || url.rfind("https://", 0) == 0;
}

}  // namespace spectra
