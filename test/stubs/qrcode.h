#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
// Minimal qrcode (ricmoo/QRCode) stub for host-side compile checks.
typedef struct QRCode {
  uint8_t version;
  uint8_t size;
  uint8_t ecc;
  uint8_t mode;
  uint8_t* modules;
} QRCode;
#ifdef __cplusplus
extern "C" {
#endif
uint16_t qrcode_getBufferSize(uint8_t version);
bool qrcode_initText(void* qrcode, uint8_t* modules, uint8_t version,
                     uint8_t ecc, const char* data);
bool qrcode_getModule(void* qrcode, uint8_t x, uint8_t y);
#ifdef __cplusplus
}
#endif
