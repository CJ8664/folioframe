#pragma once
// Image URL template: expands {seed} (random cache-buster), {width},
// {height} (panel-native geometry after rotation). Plain URLs without
// tokens pass through untouched. Pure logic (std::string).
#include <cstdint>
#include <string>

namespace spectra {

struct UrlTokens {
  uint32_t seed;
  uint16_t width;
  uint16_t height;
};

std::string expandUrlTemplate(const std::string& tpl, const UrlTokens& tok);

// Validation for portal input.
bool validImageUrl(const std::string& url);  // http(s), <= 512 chars

}  // namespace spectra
