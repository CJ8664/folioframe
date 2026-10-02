"""Local folder album source."""
import os
import random

from PIL import Image

from . import Source, pick_unseen, register

EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


@register
class FolderSource(Source):
    name = "folder"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.dir = os.path.expanduser(cfg.get("dir", "~/Pictures/frame"))
        self.rng = random.Random()

    def _ids(self):
        if not os.path.isdir(self.dir):
            return []
        return sorted(f for f in os.listdir(self.dir)
                      if f.lower().endswith(EXTS))

    def next_id(self, history):
        return pick_unseen(self._ids(), history, self.rng)

    def load(self, item_id):
        with open(os.path.join(self.dir, item_id), "rb") as f:
            img = Image.open(f)
            img.load()
        return img.convert("RGB")

    def describe(self):
        d = super().describe()
        d.update(dir=self.dir, count=len(self._ids()))
        return d
