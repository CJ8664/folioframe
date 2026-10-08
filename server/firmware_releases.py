"""Fetch and install versioned FolioFrame firmware GitHub Releases."""

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


logger = logging.getLogger("folioframe.firmware")


class FirmwareReleaseError(RuntimeError):
    pass


class FirmwareReleaseUpdater:
    REPOSITORY = "CJ8664/folioframe"
    RELEASES_URL = (
        "https://api.github.com/repos/CJ8664/folioframe/releases?per_page=100"
    )
    RELEASE_TAG = re.compile(r"^folioframe-v(\d+\.\d+\.\d+)$")
    VERSION = re.compile(r"^\d+\.\d+\.\d+$")
    BUILD = re.compile(r"^[1-9]\d{0,9}$")
    API_RESPONSE_LIMIT = 8 * 1024 * 1024
    FIRMWARE_LIMIT = 16 * 1024 * 1024
    FIRMWARE_MIN_BYTES = 1024
    METADATA_LIMIT = 64
    REQUEST_TIMEOUT_SECONDS = 15
    REFRESH_COOLDOWN_SECONDS = 300
    ASSET_HOSTS = frozenset({
        "github.com",
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
        "github-releases.githubusercontent.com",
    })

    def __init__(self, firmware_dir):
        self.firmware_dir = os.path.abspath(firmware_dir)
        self._lock = threading.Lock()
        self._last_attempt = 0.0
        self._last_result = None

    def refresh(self, current_version, current_build):
        if not self._lock.acquire(blocking=False):
            return {"ok": True, "status": "in_progress", "updated": False}
        try:
            now = time.monotonic()
            if (self._last_result is not None and
                    now - self._last_attempt < self.REFRESH_COOLDOWN_SECONDS):
                return {
                    **self._last_result,
                    "status": "cached",
                    "previous_status": self._last_result["status"],
                    "updated": False,
                }

            self._last_attempt = now
            try:
                result = self._refresh(current_version, current_build)
            except (FirmwareReleaseError, OSError, urllib.error.URLError,
                    json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.warning("Firmware release refresh failed: %s", exc)
                result = {
                    "ok": False,
                    "status": "failed",
                    "updated": False,
                    "error": str(exc),
                }
            self._last_result = result
            return dict(result)
        finally:
            self._lock.release()

    def _refresh(self, current_version, current_build):
        release = self._latest_release()
        match = self.RELEASE_TAG.fullmatch(release["tag_name"])
        version = match.group(1)
        assets = self._assets_by_name(release)
        versioned_name = f"firmware-{version}.bin"
        required = ("firmware.bin", versioned_name, "VERSION", "BUILD")
        missing = [name for name in required if name not in assets]
        if missing:
            raise FirmwareReleaseError(
                "release is missing required assets: " + ", ".join(missing))

        os.makedirs(self.firmware_dir, exist_ok=True)
        staging = tempfile.mkdtemp(prefix=".firmware-refresh-",
                                   dir=self.firmware_dir)
        try:
            downloaded = {}
            for name in ("VERSION", "BUILD"):
                target = os.path.join(staging, name)
                downloaded[name] = self._download_asset(
                    assets[name], release["tag_name"], target,
                    self.METADATA_LIMIT)

            try:
                with open(os.path.join(staging, "VERSION"), "rb") as stream:
                    published_version = stream.read().decode("ascii").strip()
                with open(os.path.join(staging, "BUILD"), "rb") as stream:
                    published_build = stream.read().decode("ascii").strip()
            except UnicodeDecodeError as exc:
                raise FirmwareReleaseError(
                    "release metadata must contain ASCII text") from exc
            if (not self.VERSION.fullmatch(published_version) or
                    published_version != version):
                raise FirmwareReleaseError(
                    "release VERSION does not match its tag")
            if not self.BUILD.fullmatch(published_build):
                raise FirmwareReleaseError(
                    "release BUILD must be a positive integer")
            if int(published_build) > 0xFFFFFFFF:
                raise FirmwareReleaseError(
                    "release BUILD exceeds the firmware counter range")

            try:
                local_build = int(current_build)
            except (TypeError, ValueError):
                local_build = 0
            remote_build = int(published_build)
            if remote_build < local_build:
                return {
                    "ok": True,
                    "status": "local_ahead",
                    "updated": False,
                    "version": current_version,
                    "build": str(local_build),
                }
            if (remote_build == local_build and current_version and
                    current_version != version):
                raise FirmwareReleaseError(
                    "release build is not newer than the installed firmware")

            targets = {
                versioned_name: versioned_name,
                "firmware.bin": "firmware.bin",
                "VERSION": "VERSION",
                "BUILD": "BUILD",
            }
            complete = all(
                os.path.isfile(os.path.join(self.firmware_dir, name))
                for name in targets.values())
            if (remote_build == local_build and current_version == version
                    and complete):
                return {
                    "ok": True,
                    "status": "up_to_date",
                    "updated": False,
                    "version": version,
                    "build": published_build,
                }

            for name in ("firmware.bin", versioned_name):
                target = os.path.join(staging, name)
                downloaded[name] = self._download_asset(
                    assets[name], release["tag_name"], target,
                    self.FIRMWARE_LIMIT)
            if downloaded["firmware.bin"] != downloaded[versioned_name]:
                raise FirmwareReleaseError(
                    "firmware.bin does not match the versioned firmware asset")
            if (os.path.getsize(os.path.join(staging, "firmware.bin")) <
                    self.FIRMWARE_MIN_BYTES):
                raise FirmwareReleaseError(
                    "firmware image is smaller than the minimum size")
            with open(os.path.join(staging, "firmware.bin"), "rb") as stream:
                if stream.read(1) != b"\xe9":
                    raise FirmwareReleaseError(
                        "firmware.bin is not a valid ESP32 app image")

            # Publish BUILD last: device OTA checks cannot observe the new
            # build number until its firmware image and metadata are in place.
            for source_name in (versioned_name, "firmware.bin", "VERSION",
                                "BUILD"):
                os.replace(
                    os.path.join(staging, source_name),
                    os.path.join(self.firmware_dir, targets[source_name]),
                )
            logger.info("Installed firmware release %s (build %s)",
                        version, published_build)
            return {
                "ok": True,
                "status": "updated",
                "updated": True,
                "version": version,
                "build": published_build,
            }
        finally:
            try:
                shutil.rmtree(staging)
            except OSError:
                logger.exception("Could not remove firmware staging directory")

    def _latest_release(self):
        request = urllib.request.Request(
            self.RELEASES_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "FolioFrame-firmware-updater",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(
                request, timeout=self.REQUEST_TIMEOUT_SECONDS) as response:
            if self._response_host(response) != "api.github.com":
                raise FirmwareReleaseError(
                    "GitHub Releases API redirected to an unexpected host")
            data = response.read(self.API_RESPONSE_LIMIT + 1)
        if len(data) > self.API_RESPONSE_LIMIT:
            raise FirmwareReleaseError(
                "GitHub Releases response exceeded the size limit")
        releases = json.loads(data.decode("utf-8"))
        if not isinstance(releases, list):
            raise FirmwareReleaseError(
                "GitHub Releases API returned an invalid response")

        candidates = []
        for release in releases:
            if not isinstance(release, dict) or release.get("draft") or \
                    release.get("prerelease"):
                continue
            tag = release.get("tag_name")
            if not isinstance(tag, str):
                continue
            match = self.RELEASE_TAG.fullmatch(tag or "")
            if match:
                candidates.append(
                    (tuple(int(part) for part in match.group(1).split(".")),
                     release))
        if not candidates:
            raise FirmwareReleaseError(
                "no stable folioframe-vX.Y.Z release was found")
        return max(candidates, key=lambda candidate: candidate[0])[1]

    @staticmethod
    def _response_host(response):
        final_url = response.geturl()
        try:
            parsed = urllib.parse.urlparse(final_url)
            port = parsed.port
        except (TypeError, ValueError):
            return ""
        if (parsed.scheme != "https" or parsed.username or parsed.password or
                port not in (None, 443)):
            return ""
        return parsed.hostname.lower() if parsed.hostname else ""

    def _assets_by_name(self, release):
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise FirmwareReleaseError("release assets are missing")
        result = {}
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = asset.get("name")
            if not isinstance(name, str) or not name:
                continue
            if name in result:
                raise FirmwareReleaseError(
                    f"release contains duplicate asset {name}")
            result[name] = asset
        return result

    def _download_asset(self, asset, tag, destination, max_bytes):
        name = asset.get("name", "")
        expected_path = (
            f"/{self.REPOSITORY}/releases/download/{tag}/{name}")
        download_url = asset.get("browser_download_url", "")
        if not isinstance(download_url, str):
            raise FirmwareReleaseError(
                f"release asset URL is invalid for {name}")
        try:
            parsed = urllib.parse.urlparse(download_url)
            port = parsed.port
        except ValueError as exc:
            raise FirmwareReleaseError(
                f"release asset URL is invalid for {name}") from exc
        if (parsed.scheme != "https" or parsed.hostname != "github.com" or
                parsed.username or parsed.password or
                port not in (None, 443) or parsed.path != expected_path or
                parsed.query or parsed.fragment):
            raise FirmwareReleaseError(
                f"release asset URL is invalid for {name}")

        declared_size = asset.get("size")
        if (type(declared_size) is not int or declared_size <= 0 or
                declared_size > max_bytes):
            raise FirmwareReleaseError(
                f"release asset size is invalid for {name}")
        request = urllib.request.Request(
            download_url,
            headers={"User-Agent": "FolioFrame-firmware-updater"},
        )
        digest = hashlib.sha256()
        total = 0
        with urllib.request.urlopen(
                request, timeout=self.REQUEST_TIMEOUT_SECONDS) as response:
            if self._response_host(response) not in self.ASSET_HOSTS:
                raise FirmwareReleaseError(
                    f"release asset {name} redirected to an unexpected host")
            with open(destination, "wb") as output:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise FirmwareReleaseError(
                            f"release asset {name} exceeded the size limit")
                    output.write(chunk)
                    digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())
        if total != declared_size:
            raise FirmwareReleaseError(
                f"release asset size mismatch for {name}")

        declared_digest = asset.get("digest")
        if declared_digest is not None:
            if not isinstance(declared_digest, str):
                raise FirmwareReleaseError(
                    f"release asset digest is invalid for {name}")
            match = re.fullmatch(r"sha256:([0-9a-f]{64})", declared_digest)
            if not match or match.group(1) != digest.hexdigest():
                raise FirmwareReleaseError(
                    f"release asset digest mismatch for {name}")
        return digest.hexdigest()
