"""Persistent Google Photos import jobs backed by the local Store."""
import logging
import threading
import time
import uuid

from sources.google_photos import PickerClient, PickFlow

logger = logging.getLogger("folioframe")


class GooglePhotosImportWorker:
    def __init__(self, store, blobs, photos_for):
        self.store = store
        self.blobs = blobs
        self.photos_for = photos_for
        self._job_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None

    def queue(self, sub, photos):
        with self._job_lock:
            current = self.store.get("gphotos_imports", sub) or {}
            if current.get("status") in ("waiting", "processing"):
                return current.get("picker_uri", "")
            session = PickerClient(photos.oauth).create_session()
            self.store.put("gphotos_imports", sub, {
                "session_id": session["id"],
                "picker_uri": session["pickerUri"],
                "status": "waiting",
                "count": 0,
                "error": "",
                "lease_owner": "",
                "lease_until": 0,
                "updated_at": time.time(),
            })
            self._wake.set()
            return session["pickerUri"]

    def start(self):
        self._stop.clear()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._run, name="gphotos-import-worker", daemon=True)
            self._thread.start()
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self):
        while not self._stop.is_set():
            self._wake.clear()
            try:
                if self._process_next():
                    continue
            except Exception:
                logger.exception("Google Photos import worker failed")
            self._wake.wait(10)

    def _process_next(self):
        jobs = [(sub, job) for sub, job in
                self.store.all("gphotos_imports").items()
                if isinstance(job, dict)]
        for sub, job in sorted(
                jobs, key=lambda pair: pair[1].get("updated_at", 0)):
            if job.get("status") not in ("waiting", "processing"):
                continue
            owner = uuid.uuid4().hex
            claimed = self.store.claim(
                "gphotos_imports", sub, owner, lease_seconds=120)
            if claimed is None:
                continue
            self._process(sub, claimed, owner)
            return True
        return False

    def _process(self, sub, job, owner):
        heartbeat_stop = threading.Event()

        def renew_lease():
            while not heartbeat_stop.wait(30):
                if self._stop.is_set():
                    return
                try:
                    if not self.store.renew_claim(
                            "gphotos_imports", sub, owner, 120):
                        logger.warning(
                            "Google Photos import lease lost for user %s", sub)
                        return
                except Exception:
                    logger.exception(
                        "Could not renew Google Photos import lease")
                    return

        heartbeat = threading.Thread(
            target=renew_lease, name="gphotos-import-lease", daemon=True)
        heartbeat.start()
        try:
            photos = self.photos_for(sub)
            client = PickerClient(photos.oauth)

            def mark_importing():
                if not self.store.renew_claim(
                        "gphotos_imports", sub, owner, 120,
                        status="processing"):
                    raise RuntimeError("Google Photos import lease lost")

            count = PickFlow(
                client, photos.cache_dir, blob_store=self.blobs,
                blob_prefix=photos.blob_prefix,
            ).run(job["session_id"], cleanup_session=False,
                  on_ready=mark_importing)
        except Exception as e:
            logger.error("Google Photos import failed (%s)", type(e).__name__)
            saved = self.store.finish_claim(
                "gphotos_imports", sub, owner,
                {"status": "error", "error": str(e)})
            if not saved:
                logger.warning(
                    "Could not record Google Photos import failure for user %s",
                    sub)
        else:
            saved = self.store.finish_claim(
                "gphotos_imports", sub, owner,
                {"status": "done", "count": count, "error": ""})
            if saved:
                try:
                    client.delete_session(job["session_id"])
                except Exception:
                    logger.exception(
                        "Could not clean up completed Google Photos session")
            else:
                logger.warning(
                    "Could not record Google Photos import completion for user %s",
                    sub)
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=1)
