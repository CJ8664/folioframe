"""Pluggable token persistence for OAuth token sets.

FileTokenStore: local JSON file (0600) -- local dev, home lab.
FirestoreTokenStore: a Firestore document -- Cloud Run, where the local
disk is ephemeral.
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


class FirestoreTokenStore(TokenStore):
    def __init__(self, client, doc_path="service/tokens/gphotos"):
        self._doc = client.document(doc_path)

    def load(self):
        snap = self._doc.get()
        return snap.to_dict() if snap.exists else None

    def save(self, tokens):
        self._doc.set(dict(tokens))

    def clear(self):
        self._doc.delete()
