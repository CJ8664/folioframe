"""Dashboard source: clock + date + weather, PIL-rendered.

Weather via Open-Meteo (no API key). Drawn in high-contrast primaries on
white so the 6-color dither stays clean.
"""
import datetime
import json
import urllib.request

from PIL import Image, ImageDraw, ImageFont

from . import Source, register

WMO = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Icy fog", 51: "Light drizzle", 53: "Drizzle",
    55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 80: "Showers",
    81: "Showers", 82: "Violent showers", 95: "Thunderstorm",
    96: "Storm + hail", 99: "Storm + hail",
}

WHITE, BLACK, RED, BLUE, YELLOW = (
    (255, 255, 255), (20, 20, 20), (200, 40, 40), (40, 70, 200),
    (240, 200, 40))


def _font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _weather(lat, lon):
    url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
           "&current=temperature_2m,weather_code&"
           "daily=temperature_2m_max,temperature_2m_min&timezone=auto" % (lat, lon))
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            j = json.load(r)
        cur = j["current"]
        day = j["daily"]
        return {"temp": round(cur["temperature_2m"]),
                "code": cur["weather_code"],
                "hi": round(day["temperature_2m_max"][0]),
                "lo": round(day["temperature_2m_min"][0])}
    except Exception:
        return None


@register
class DashboardSource(Source):
    name = "dashboard"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.lat = cfg.get("lat", 36.17)   # Las Vegas default
        self.lon = cfg.get("lon", -115.14)
        self.tz = cfg.get("timezone", "America/Los_Angeles")

    def next_id(self, history):
        return "now"  # always re-render

    def load(self, item_id):
        W, H = 1200, 1600
        img = Image.new("RGB", (W, H), WHITE)
        d = ImageDraw.Draw(img)
        now = datetime.datetime.now(datetime.timezone.utc).astimezone()
        # Timezone override via config when available
        try:
            from zoneinfo import ZoneInfo
            now = now.astimezone(ZoneInfo(self.tz))
        except Exception:
            pass

        d.text((80, 140), now.strftime("%H:%M"), font=_font(340), fill=BLACK)
        d.text((90, 520), now.strftime("%A, %B %d").upper(),
               font=_font(72), fill=BLUE)
        d.line((80, 660, W - 80, 660), fill=BLACK, width=6)

        w = _weather(self.lat, self.lon)
        y = 740
        if w:
            d.text((80, y), f"{w['temp']}°", font=_font(300), fill=RED)
            d.text((90, y + 330), WMO.get(w["code"], "Weather").upper(),
                   font=_font(80), fill=BLACK)
            d.text((90, y + 440), f"H {w['hi']}°   L {w['lo']}°",
                   font=_font(80), fill=BLUE)
        else:
            d.text((80, y), "Weather", font=_font(120), fill=BLACK)
            d.text((90, y + 170), "OFFLINE", font=_font(80), fill=RED)

        d.rectangle((0, H - 120, W, H), fill=YELLOW)
        d.text((80, H - 95), "SPECTRAFRAME", font=_font(56), fill=BLACK)
        return img

    def describe(self):
        d = super().describe()
        d.update(lat=self.lat, lon=self.lon)
        return d
