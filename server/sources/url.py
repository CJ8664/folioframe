"""Fixed URL-template source: fetch {seed} URLs per rotation."""
import random
import urllib.request
from io import BytesIO

from PIL import Image

from . import Source, register


@register
class UrlSource(Source):
    name = "url"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.template = cfg.get(
            "template", "https://picsum.photos/seed/{seed}/1200/1600")
        self.rng = random.Random()

    def next_id(self, history):
        for _ in range(200):
            seed = str(self.rng.randrange(1 << 31))
            if seed not in history[-50:]:
                return seed
        return str(self.rng.randrange(1 << 31))

    def load(self, item_id):
        url = self.template.replace("{seed}", item_id)
        req = urllib.request.Request(url, headers={"User-Agent": "spectra-frame"})
        with urllib.request.urlopen(req, timeout=30) as r:
            img = Image.open(BytesIO(r.read()))
            img.load()
        return img.convert("RGB")

    def describe(self):
        d = super().describe()
        d.update(template=self.template)
        return d
