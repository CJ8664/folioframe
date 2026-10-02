#pragma once
// Quiet-hours policy: a daily no-refresh window [startMin, endMin) in
// minutes-since-midnight, local time. Wraps midnight. startMin == endMin
// means "no quiet window". Pure logic — no hardware deps.
#include <cstdint>

namespace spectra {

bool inQuietWindow(int nowMin, int startMin, int endMin);

// Seconds from nowMin until endMin, wrapping midnight. Only call when
// inQuietWindow(nowMin, startMin, endMin) is true.
uint32_t secondsToWindowEnd(int nowMin, int endMin);

}  // namespace spectra
