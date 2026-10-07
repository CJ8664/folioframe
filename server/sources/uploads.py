"""Per-user uploads library source.

Each user gets their own uploads directory
(<data_dir>/users/<sub>/uploads). Photos uploaded through the web console
land here and become a selectable photo source for their frames.
"""
import os

from .folder import FolderSource
from . import register


@register
class UploadsSource(FolderSource):
    name = "uploads"

    def __init__(self, cfg):
        # dir is injected per-user by the server; fall back to a shared
        # default only if unset (never used in production).
        cfg = dict(cfg)
        cfg.setdefault("dir", os.path.expanduser("~/.folioframe/uploads"))
        super().__init__(cfg)

    def describe(self):
        d = super().describe()
        d.update(kind="uploads")
        return d
