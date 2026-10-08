"""JSON-file storage for SpectraFrame service state."""
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

    def claim(self, collection, key, owner, lease_seconds):
        raise NotImplementedError

    def renew_claim(self, collection, key, owner, lease_seconds):
        raise NotImplementedError

    def finish_claim(self, collection, key, owner, updates):
        raise NotImplementedError


class JsonStore(Store):
    """Single JSON file, atomic writes, file mode 0600 (holds token hashes)."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.data = {"users": {}, "devices": {}, "sessions": {}}
        if os.path.exists(path):
            try:
                with open(path) as f:
                    loaded = json.load(f)
            except (ValueError, OSError) as e:
                # Corrupt registry (truncated write, disk issue): quarantine
                # it and start clean rather than crash-looping the server,
                # which would brick pairing for every device.
                backup = "%s.corrupt.%d" % (path, int(time.time()))
                try:
                    os.replace(path, backup)
                except OSError:
                    pass
                print("WARNING: %s unreadable (%s); quarantined to %s, "
                      "starting with empty state" % (path, e, backup))
                loaded = {}
            if not isinstance(loaded, dict):
                loaded = {}
            self.data.update({k: v for k, v in loaded.items()
                              if isinstance(v, dict)})
        else:
            self._save_locked()

    def _save_locked(self):
        tmp = self.path + ".tmp"
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(self.data, f)
            # Ensure data hits disk before the rename: without fsync a
            # power loss can lose recent writes or expose a zero-length file.
            f.flush()
            os.fsync(f.fileno())
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

    def claim(self, collection, key, owner, lease_seconds):
        with self.lock:
            record = self.data.get(collection, {}).get(key)
            if not isinstance(record, dict) or record.get("status") not in (
                    "waiting", "processing"):
                return None
            now = time.time()
            if record.get("lease_until", 0) > now:
                return None
            claimed = dict(record, lease_owner=owner,
                           lease_until=now + lease_seconds,
                           updated_at=now)
            self.data[collection][key] = claimed
            self._save_locked()
            return claimed

    def renew_claim(self, collection, key, owner, lease_seconds, status=None):
        with self.lock:
            record = self.data.get(collection, {}).get(key)
            if (not isinstance(record, dict) or
                    record.get("lease_owner") != owner or
                    record.get("lease_until", 0) <= time.time()):
                return False
            updates = {"lease_until": time.time() + lease_seconds,
                       "updated_at": time.time()}
            if status is not None:
                updates["status"] = status
            renewed = dict(record, **updates)
            self.data[collection][key] = renewed
            self._save_locked()
            return True

    def finish_claim(self, collection, key, owner, updates):
        with self.lock:
            record = self.data.get(collection, {}).get(key)
            if (not isinstance(record, dict) or
                    record.get("lease_owner") != owner):
                return False
            finished = dict(record, **updates, lease_owner="", lease_until=0,
                            updated_at=time.time())
            self.data[collection][key] = finished
            self._save_locked()
            return True
