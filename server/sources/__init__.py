"""Content source interface + registry.

A source produces item ids and renders them to PIL images.
Rotation state (shown history) is managed by the server; sources only
need to honor it in next_id().
"""
import random

SOURCES = {}


def register(cls):
    SOURCES[cls.name] = cls
    return cls


class Source:
    name = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def next_id(self, history: list) -> str | None:
        """Pick the next item id given recent history (most-recent last)."""
        raise NotImplementedError

    def load(self, item_id: str):
        """Return a PIL Image for the item id."""
        raise NotImplementedError

    def describe(self) -> dict:
        return {"name": self.name}


def pick_unseen(ids: list, history: list, rng: random.Random) -> str | None:
    """Unseen-first, shuffled; reshuffles when everything was seen."""
    if not ids:
        return None
    unseen = [i for i in ids if i not in history]
    pool = unseen or ids
    return rng.choice(pool)
