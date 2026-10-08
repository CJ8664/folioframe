"""Pluggable token persistence for OAuth token sets.

FileTokenStore: local JSON file (0600) -- local dev, home lab.
StoreTokenStore: tokens live in the server Store (JsonStore), one entry per
user. The server uses this for per-user Google Photos tokens.
"""
import json
import os


class TokenStore:
    def load(self):
        """Stored token dict, or None."""
        raise NotImplementedError

    def save(self, tokens):
        raise NotImplementedError

    def clear(self):
        raise NotImplementedError


class FileTokenStore(TokenStore):
    def __init__(self, path):
        self.path = path

    def load(self):
        if not os.path.exists(self.path):
            return None
        with open(self.path) as f:
            return json.load(f)

    def save(self, tokens):
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(tokens, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def clear(self):
        if os.path.exists(self.path):
            os.remove(self.path)


class StoreTokenStore(TokenStore):
    """OAuth tokens keyed per user inside the server Store.

    collection "photos_tokens", key = Google sub. Works unchanged on
    JsonStore.
    """

    def __init__(self, store, sub):
        self._store = store
        self._sub = sub

    def load(self):
        return self._store.get("photos_tokens", self._sub)

    def save(self, tokens):
        self._store.put("photos_tokens", self._sub, dict(tokens))

    def clear(self):
        self._store.delete("photos_tokens", self._sub)
