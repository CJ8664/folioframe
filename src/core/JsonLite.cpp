#include "JsonLite.h"

namespace spectra {

namespace {

// Find the value position for "key": locate `"key"`, then `:`, then the
// first non-whitespace char. Returns npos on any mismatch.
size_t valuePos(const std::string& body, const std::string& key) {
  std::string quoted = "\"" + key + "\"";
  size_t k = body.find(quoted);
  if (k == std::string::npos) return std::string::npos;
  size_t p = k + quoted.size();
  while (p < body.size() &&
         (body[p] == ' ' || body[p] == '\t' || body[p] == '\n' ||
          body[p] == '\r'))
    p++;
  if (p >= body.size() || body[p] != ':') return std::string::npos;
  p++;
  while (p < body.size() &&
         (body[p] == ' ' || body[p] == '\t' || body[p] == '\n' ||
          body[p] == '\r'))
    p++;
  return p < body.size() ? p : std::string::npos;
}

}  // namespace

std::string jsonString(const std::string& body, const std::string& key) {
  size_t p = valuePos(body, key);
  if (p == std::string::npos || body[p] != '"') return "";
  std::string out;
  for (size_t i = p + 1; i < body.size(); i++) {
    char c = body[i];
    if (c == '\\' && i + 1 < body.size()) {
      char e = body[++i];
      // Decode the escapes the server can emit; pass the rest through.
      out += (e == 'n' ? '\n' : e == 't' ? '\t' : e == 'r' ? '\r' : e);
    } else if (c == '"') {
      return out;  // closing quote
    } else {
      out += c;
    }
  }
  return "";  // unterminated: treat as absent
}

bool jsonOk(const std::string& body) {
  size_t p = valuePos(body, "ok");
  if (p == std::string::npos) return false;
  // Accept: true (and only true).
  return body.compare(p, 4, "true") == 0 &&
         (p + 4 >= body.size() || body[p + 4] == ',' || body[p + 4] == '}' ||
          body[p + 4] == ' ' || body[p + 4] == '\t' || body[p + 4] == '\n' ||
          body[p + 4] == '\r');
}

}  // namespace spectra
