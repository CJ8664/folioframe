"""Blob storage abstraction.

LocalBlobStore: files under a root dir (local dev, home lab).
GCSBlobStore: Google Cloud Storage bucket (Firebase/Cloud Run).

Used for device override frames/previews and the Google Photos cache --
both must survive container restarts, so Cloud Run deployments use GCS.
"""
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
        if safe.startswith(".."):
            raise ValueError("bad blob key")
        return os.path.join(self.root, safe)

    def put(self, key, data, content_type="application/octet-stream"):
        p = self._path(key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)

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


class GCSBlobStore(BlobStore):
    def __init__(self, bucket_name, client=None):
        if client is None:
            from google.cloud import storage as gcs
            client = gcs.Client()
        self._client = client
        self._bucket = self._client.bucket(bucket_name)

    def put(self, key, data, content_type="application/octet-stream"):
        self._bucket.blob(key).upload_from_string(
            data, content_type=content_type)

    def get(self, key):
        blob = self._bucket.blob(key)
        return blob.download_as_bytes() if blob.exists() else None

    def exists(self, key):
        return self._bucket.blob(key).exists()

    def delete(self, key):
        blob = self._bucket.blob(key)
        if blob.exists():
            blob.delete()

    def list(self, prefix):
        return sorted(b.name for b in
                      self._client.list_blobs(self._bucket, prefix=prefix))
