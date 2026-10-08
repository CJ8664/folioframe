#pragma once
// EinkLayout — Warm Clay layout helpers for 1200x1600 Spectra 6.
//
// Wraps a TFT_eSprite (the panel's framebuffer) with the layout primitives
// from the approved mockups: header, topline, rules, step circles, network
// card, QR cards. Uses EinkTheme ink constants (raw sprite nibbles).
//
// This does NOT weaken the Panel HAL seam: Gdeb0709e01Panel owns an
// EinkLayout and uses it inside drawStatus/drawSetupQR. Panel.h is untouched.

#include <stdint.h>

class TFT_eSprite;

namespace folioframe {

class EinkLayout {
 public:
  explicit EinkLayout(TFT_eSprite* sprite) : s_(sprite) {}

  // Fill the whole screen with paper white.
  void clear();

  // Text helpers. datum: 0=TL, 1=TC, 2=TR, 3=ML, 4=MC, 5=MR, 6=BL, 7=BC, 8=BR
  // (matches TFT_eSPI datum constants).
  void text(int x, int y, const char* str, uint8_t font, uint8_t textSize,
            uint16_t color, uint8_t datum = 0);
  void textLeft(int x, int y, const char* str, uint8_t font, uint8_t textSize,
                uint16_t color) {
    text(x, y, str, font, textSize, color, 0);
  }
  void textCenter(int cx, int y, const char* str, uint8_t font,
                  uint8_t textSize, uint16_t color) {
    text(cx, y, str, font, textSize, color, 4);
  }

  // "FolioFrame Setup" header, 78px, left-aligned at (80,130).
  // Drawn on every setup/status screen until pairing (per mockups).
  void header();

  // Sage uppercase topline, 16px, at (82,67). E.g. "FOLIOFRAME SETUP".
  // Manual letter-spacing (drawString has no tracking): pass pre-spaced text.
  void topline(const char* spacedText);

  // Thin black rule from x=82 to x=1118 at y.
  void rule(int y);

  // Numbered step circle: 58px diameter, black ring, number centered.
  // (Mockup uses sage-fill; black ring reads better in 6 inks.)
  void stepCircle(int cx, int y, int n);

  // Red rounded card with white AP name, per mockup §1.3 #6.
  // Card: (82,326,1036,132), radius 18.
  void networkCard(const char* apName);

  // Labeled QR card: white card with 2px black border, green uppercase
  // label, 248px QR, red URL below. Card is 470px tall.
  void qrCard(int x, int y, int w, const char* label, const char* heading,
              const char* qrText, const char* url);

  // Draw a QR code (version 6, black on white) at (x,y) with target size.
  void qr(const char* text, int x, int y, int targetSize);

  // Small help QR + "Scan for help" caption, bottom-right.
  // 296px QR at (1200-76-296, 1600-64-296-40).
  void helpQR();

 private:
  TFT_eSprite* s_;
};

}  // namespace folioframe
