"""Filesystem blob storage for device overrides and the Google Photos cache."""
import os


class BlobStore:
    def put(self, key, data, content_type="application/octet-stream"):
        raise NotImplementedError

    def get(self, key):
        """Bytes, or None if missing."""
        raise NotImplementedError

    def exists(self, key):
        raise NotImplementedError

    def delete(self, key):
        raise NotImplementedError

    def list(self, prefix):
        """Keys starting with prefix."""
        raise NotImplementedError


class LocalBlobStore(BlobStore):
    def __init__(self, root):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _path(self, key):
        # keep keys inside the root even if a caller passes something odd
        safe = os.path.normpath(key).lstrip(os.sep)
        if safe.startswith("..") or safe in (".", ""):
            raise ValueError("bad blob key")
        return os.path.join(self.root, safe)

    def put(self, key, data, content_type="application/octet-stream"):
        p = self._path(key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        # Atomic write: crash mid-write leaves the old file intact,
        # never a truncated/corrupt blob.
        tmp = p + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, p)

    def get(self, key):
        p = self._path(key)
        if not os.path.exists(p):
            return None
        with open(p, "rb") as f:
            return f.read()

    def exists(self, key):
        return os.path.exists(self._path(key))

    def delete(self, key):
        p = self._path(key)
        if os.path.exists(p):
            os.remove(p)

    def list(self, prefix):
        out = []
        for dirpath, _, files in os.walk(self.root):
            for fn in files:
                full = os.path.join(dirpath, fn)
                key = os.path.relpath(full, self.root).replace(os.sep, "/")
                if key.startswith(prefix):
                    out.append(key)
        return sorted(out)
