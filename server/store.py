"""Storage abstraction for SpectraFrame service state.

Phase 1 ships JsonStore (local JSON files). FirestoreStore (or any other
backend) can implement the same Store interface later without touching
callers -- see docs/SYSTEM_PLAN.md section 2.4.
"""
import json
import os
import threading
import time


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


class FirestoreStore(Store):
    """Firestore backend. Layout: {collection}/{key} documents.

    Sessions get a server-side expiry timestamp so stale sessions can be
    swept; reads filter them out. Uses the Admin SDK (Application Default
    Credentials on Cloud Run); Firestore *security rules do not apply* to
    this path, so firestore.rules denies all client access.
    """

    def __init__(self, project_id=None, client=None):
        if client is None:
            from google.cloud import firestore
            client = firestore.Client(project=project_id)
        self._client = client

    def doc(self, path):
        return self._client.document(path)

    def _ref(self, collection, key):
        return self._client.collection(collection).document(key)

    def get(self, collection, key, default=None):
        snap = self._ref(collection, key).get()
        if not snap.exists:
            return default
        data = snap.to_dict()
        if collection == "sessions" and data.get("expires_at", 0) < \
                time.time():
            self._ref(collection, key).delete()
            return default
        return data.get("value", default)

    def put(self, collection, key, value):
        data = {"value": value}
        if collection == "sessions":
            data["expires_at"] = time.time() + 24 * 3600
        self._ref(collection, key).set(data)

    def delete(self, collection, key):
        self._ref(collection, key).delete()

    def all(self, collection):
        out = {}
        now = time.time()
        for snap in self._client.collection(collection).stream():
            data = snap.to_dict()
            if collection == "sessions" and \
                    data.get("expires_at", 0) < now:
                continue
            out[snap.id] = data.get("value", {})
        return out
