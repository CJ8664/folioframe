#include <Arduino.h>
#include <Seeed_GFX.h>

Seeed_GFX display(Seeed_Product::Seeed_ePaper_7INCH09_C);

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("=== Minimal Display Test ===");
    
    Serial.println("Calling display.begin()...");
    if (!display.begin()) {
        Serial.print("begin FAILED: ");
        Serial.println(display.lastResult().message);
        return;
    }
    Serial.println("display.begin() OK");
    
    Serial.println("Drawing...");
    display.fillScreen(TFT_WHITE);
    display.setTextColor(TFT_BLACK);
    display.setTextSize(4);
    display.drawString("Minimal Test", 100, 100);
    display.drawString("If you see this,", 100, 200);
    display.drawString("the panel works!", 100, 300);
    
    Serial.println("Calling display.update()...");
    unsigned long start = millis();
    display.update();
    unsigned long elapsed = millis() - start;
    Serial.print("update done in ");
    Serial.print(elapsed);
    Serial.println("ms");
    
    if (elapsed < 10000) {
        Serial.println("WARN: refresh was too fast, panel may not have executed it");
    } else {
        Serial.println("Refresh took expected time - check the panel!");
    }
    
    Serial.println("=== Test complete, halting ===");
}

void loop() {
    delay(1000);
}
