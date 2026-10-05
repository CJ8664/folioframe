"""picsum.photos random-image source (no API key)."""
import random
import urllib.request
from io import BytesIO

from . import Source, register

# Same rationale as sources/url.py: never read an unbounded body.
MAX_DOWNLOAD = 25 * 1024 * 1024


def _read_capped(resp):
    chunks, total = [], 0
    while True:
        chunk = resp.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_DOWNLOAD:
            raise ValueError("download too large")
        chunks.append(chunk)
    return b"".join(chunks)


@register
class PicsumSource(Source):
    name = "picsum"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.rng = random.Random()
        self.w = int(cfg.get("width", 1200))
        self.h = int(cfg.get("height", 1600))

    def next_id(self, history):
        for _ in range(200):  # avoid recent repeats
            seed = str(self.rng.randrange(1 << 31))
            if seed not in history[-50:]:
                return seed
        return str(self.rng.randrange(1 << 31))

    def load(self, item_id):
        url = f"https://picsum.photos/seed/{item_id}/{self.w}/{self.h}"
        req = urllib.request.Request(url, headers={"User-Agent": "spectra-frame"})
        with urllib.request.urlopen(req, timeout=30) as r:
            from PIL import Image
            img = Image.open(BytesIO(_read_capped(r)))
            img.load()
        return img.convert("RGB")
