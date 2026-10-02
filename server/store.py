"""Storage abstraction for SpectraFrame service state.

Phase 1 ships JsonStore (local JSON files). FirestoreStore (or any other
backend) can implement the same Store interface later without touching
callers -- see docs/SYSTEM_PLAN.md section 2.4.
"""
import json
import os
import threading


class Store:
    """Interface: users, devices, sessions keyed collections."""

    def get(self, collection, key, default=None):
        raise NotImplementedError

    def put(self, collection, key, value):
        raise NotImplementedError

    def delete(self, collection, key):
        raise NotImplementedError

    def all(self, collection):
        raise NotImplementedError


class JsonStore(Store):
    """Single JSON file, atomic writes, file mode 0600 (holds token hashes)."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.data = {"users": {}, "devices": {}, "sessions": {}}
        if os.path.exists(path):
            with open(path) as f:
                loaded = json.load(f)
            for k in self.data:
                if isinstance(loaded.get(k), dict):
                    self.data[k] = loaded[k]
        else:
            self._save_locked()

    def _save_locked(self):
        tmp = self.path + ".tmp"
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(self.data, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def get(self, collection, key, default=None):
        with self.lock:
            return self.data.get(collection, {}).get(key, default)

    def put(self, collection, key, value):
        with self.lock:
            self.data.setdefault(collection, {})[key] = value
            self._save_locked()

    def delete(self, collection, key):
        with self.lock:
            self.data.get(collection, {}).pop(key, None)
            self._save_locked()

    def all(self, collection):
        with self.lock:
            return dict(self.data.get(collection, {}))
