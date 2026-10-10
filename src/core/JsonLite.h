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

// Boolean value of "key", or dflt if missing / not a JSON true|false.
// Whitespace-tolerant; accepts only the literals true and false.
bool jsonBool(const std::string& body, const std::string& key, bool dflt);

// Boolean value of "key" nested inside the top-level object "outer"
// (e.g. settings.auto_update), or dflt if the object/key is missing.
// The inner object must be flat (no objects nested inside it).
bool jsonNestedBool(const std::string& body, const std::string& outer,
                    const std::string& key, bool dflt);

// Integer value of "key", or dflt if missing / not an integer literal.
// Whitespace-tolerant; accepts an optional leading '-'.
int jsonInt(const std::string& body, const std::string& key, int dflt);

// Integer value of "key" nested inside the top-level object "outer"
// (e.g. settings.interval_minutes), or dflt if the object/key is missing.
int jsonNestedInt(const std::string& body, const std::string& outer,
                  const std::string& key, int dflt);

// Decoded string value of "key" nested inside the top-level object "outer",
// or "" if missing / not a string.
std::string jsonNestedString(const std::string& body, const std::string& outer,
                             const std::string& key);

}  // namespace spectra
