# Seeed_GFX v1 — low-level SPI write primitives (extracted verbatim)

Source: `.pio/libdeps/ee02/Seeed_GFX/TFT_eSPI.cpp` (lines cited), ESP32-S3 build.
Macros: `Processors/TFT_eSPI_ESP32_S3.h`.

## Macro semantics (ESP32-S3)

- `CS_L` / `CS_H` drive **TFT_CS only** (CS0 = GPIO44). They never touch TFT_CS1.
- `DC_C` / `DC_D` drive the TFT_DC pin low/high (command vs data).
- The second chip-select (CS1 = GPIO41) is handled **explicitly** by the panel
  driver via `digitalWrite(TFT_CS1, ...)` inside the init macros in
  `GDEB0709E01_Defines.h` — not by these primitives.

## begin_tft_write / end_tft_write (TFT_eSPI.cpp:84-130)

```cpp
inline void TFT_eSPI::begin_tft_write(void){
  if (locked) {
    locked = false; // Flag to show SPI access now unlocked
#if defined (SPI_HAS_TRANSACTION) && defined (SUPPORT_TRANSACTIONS) && !defined(TFT_PARALLEL_8_BIT) && !defined(RP2040_PIO_INTERFACE)
    spi.beginTransaction(SPISettings(SPI_FREQUENCY, MSBFIRST, TFT_SPI_MODE));
#endif
    CS_L;
    SET_BUS_WRITE_MODE;  // Some processors (e.g. ESP32) allow recycling the tx buffer when rx is not used
  }
}

inline void TFT_eSPI::end_tft_write(void){
  if(!inTransaction) {      // Flag to stop ending transaction during multiple graphics calls
    if (!locked) {          // Locked when beginTransaction has been called
      locked = true;        // Flag to show SPI access now locked
      SPI_BUSY_CHECK;       // Check send complete and clean out unused rx data
      CS_H;
      SET_BUS_READ_MODE;    // In case bus has been configured for tx only
#if defined (SPI_HAS_TRANSACTION) && defined (SUPPORT_TRANSACTIONS) && !defined(TFT_PARALLEL_8_BIT) && !defined(RP2040_PIO_INTERFACE)
    spi.endTransaction();
#endif
    }
  }
}
```

## writecommand (TFT_eSPI.cpp:1272-1286)

```cpp
void TFT_eSPI::writecommand(uint8_t c)
{
  begin_tft_write();

  DC_C;

  tft_Write_8(c);

  DC_D;

  end_tft_write();
}
```

Note: every `writecommand` call asserts and then de-asserts CS0 around a
**single command byte**. During the panel init sequence the dual-CS macros in
`GDEB0709E01_Defines.h` hold CS1 low across the whole command stream while CS0
toggles per byte — read those macros to see the exact interleaving.

## writedata / writecommanddata (TFT_eSPI.cpp:1338-1383)

```cpp
void TFT_eSPI::writedata(uint8_t d)
{
  begin_tft_write();

  DC_D;        // Play safe, but should already be in data mode

  tft_Write_8(d);

  CS_L;        // Allow more hold time for low VDI rail

  end_tft_write();
}

void TFT_eSPI::writecommanddata(uint8_t c,const uint8_t* d, uint16_t dataLength)
{
  begin_tft_write();
  DC_C;        // Play safe, but should already be in command mode
  tft_Write_8(c);
  DC_D;        // Play safe, but should already be in data mode

  for(int i = 0; i < dataLength; i++)
  {
    tft_Write_8(d[i]);
  }
  CS_L;        // Allow more hold time for low VDI rail
  end_tft_write();
}
```

Note the trailing `CS_L` before `end_tft_write()` in the data variants
("allow more hold time for low VDI rail") — `end_tft_write` then raises CS_H.
