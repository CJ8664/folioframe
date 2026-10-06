#pragma once
// JsonLite: a tiny JSON string-value extractor for the small, flat objects
// the FolioFrame server returns (device register / claim responses).
//
// Deliberately NOT a general parser: it finds one top-level "key" and
// returns its decoded string value, handling \" and \\ escapes. Returns ""
// when the key is absent or not a JSON string. Keeps the firmware free of a
// JSON library dependency.
#include <string>

namespace spectra {

// Decoded string value of "key", or "" if missing / not a string.
std::string jsonString(const std::string& body, const std::string& key);

// True when the body contains "ok":true (whitespace-tolerant).
bool jsonOk(const std::string& body);

}  // namespace spectra
