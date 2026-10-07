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

    def save(self, item_id, data):
        """Replace a photo's bytes (e.g. after user edit)."""
        # Validate item_id to prevent path traversal
        if not item_id or "/" in item_id or "\\" in item_id or item_id.startswith("."):
            raise ValueError("invalid item_id")
        path = os.path.join(self.dir, item_id)
        # Ensure the path is within self.dir
        if not os.path.abspath(path).startswith(os.path.abspath(self.dir)):
            raise ValueError("invalid item_id")
        with open(path, "wb") as f:
            f.write(data)

    def get_metadata(self, item_id):
        """Return basic file metadata, or None if not found."""
        try:
            path = os.path.join(self.dir, item_id)
            if not os.path.exists(path):
                return None
            st = os.stat(path)
            return {
                "id": item_id,
                "filename": item_id,
                "size": st.st_size,
                "modified": int(st.st_mtime),
                "source": self.name,
            }
        except Exception:
            return None
