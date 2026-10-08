import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from firmware_releases import FirmwareReleaseUpdater


class FakeResponse:
    def __init__(self, body, final_url):
        self.body = io.BytesIO(body)
        self.final_url = final_url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.body.close()

    def read(self, size=-1):
        return self.body.read(size)

    def geturl(self):
        return self.final_url


def release(version="0.0.12", build="30", firmware=b"\xe9new firmware"):
    firmware = firmware.ljust(1024, b"\x00")
    tag = f"folioframe-v{version}"
    names = ("firmware.bin", f"firmware-{version}.bin", "VERSION", "BUILD")
    contents = {
        "firmware.bin": firmware,
        f"firmware-{version}.bin": firmware,
        "VERSION": version.encode("ascii"),
        "BUILD": build.encode("ascii"),
    }
    assets = []
    for name in names:
        data = contents[name]
        assets.append({
            "name": name,
            "size": len(data),
            "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
            "browser_download_url":
                f"https://github.com/CJ8664/folioframe/releases/download/"
                f"{tag}/{name}",
        })
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "assets": assets,
    }, contents


def set_asset_contents(release_data, contents, name, data):
    contents[name] = data
    asset = next(item for item in release_data["assets"]
                 if item["name"] == name)
    asset["size"] = len(data)
    asset["digest"] = "sha256:" + hashlib.sha256(data).hexdigest()


class FirmwareReleaseUpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.firmware_dir = self.temp.name
        self.updater = FirmwareReleaseUpdater(self.firmware_dir)

    def tearDown(self):
        self.temp.cleanup()

    def mocked_opener(self, releases, contents):
        def open_url(request, timeout):
            url = request.full_url
            if url.startswith(self.updater.RELEASES_URL.split("?")[0]):
                return FakeResponse(
                    json.dumps(releases).encode("utf-8"),
                    self.updater.RELEASES_URL,
                )
            name = os.path.basename(urlparse(url).path)
            return FakeResponse(
                contents[name],
                f"https://release-assets.githubusercontent.com/{name}",
            )
        return open_url

    def test_installs_newest_stable_release_and_retains_history(self):
        latest, contents = release()
        older, _ = release("0.0.11", "29", b"\xe9old firmware")
        prerelease, _ = release("0.0.13", "31", b"\xe9preview")
        prerelease["prerelease"] = True
        with open(os.path.join(self.firmware_dir, "firmware-0.0.10.bin"),
                  "wb") as stream:
            stream.write(b"older published image")

        with patch("firmware_releases.urllib.request.urlopen",
                   side_effect=self.mocked_opener(
                       [older, prerelease, latest], contents)):
            result = self.updater.refresh("0.0.11", "29")

        self.assertTrue(result["ok"])
        self.assertTrue(result["updated"])
        self.assertEqual(result["version"], "0.0.12")
        self.assertEqual(result["build"], "30")
        for name in ("firmware.bin", "firmware-0.0.12.bin",
                     "VERSION", "BUILD"):
            with open(os.path.join(self.firmware_dir, name), "rb") as stream:
                self.assertEqual(stream.read(), contents[name])
        self.assertTrue(os.path.isfile(
            os.path.join(self.firmware_dir, "firmware-0.0.10.bin")))

    def test_up_to_date_check_is_cached(self):
        latest, contents = release()
        with open(os.path.join(self.firmware_dir, "firmware.bin"), "wb") as f:
            f.write(contents["firmware.bin"])
        with open(os.path.join(self.firmware_dir, "firmware-0.0.12.bin"),
                  "wb") as f:
            f.write(contents["firmware-0.0.12.bin"])
        with open(os.path.join(self.firmware_dir, "VERSION"), "wb") as f:
            f.write(contents["VERSION"])
        with open(os.path.join(self.firmware_dir, "BUILD"), "wb") as f:
            f.write(contents["BUILD"])
        opener = self.mocked_opener([latest], contents)
        with patch("firmware_releases.urllib.request.urlopen",
                   side_effect=opener) as mocked:
            result = self.updater.refresh("0.0.12", "30")
            cached = self.updater.refresh("0.0.12", "30")

        self.assertEqual(result["status"], "up_to_date")
        self.assertEqual(cached["status"], "cached")
        self.assertEqual(cached["previous_status"], "up_to_date")
        self.assertEqual(mocked.call_count, 3)

    def test_invalid_firmware_is_rejected_without_replacing_current_files(self):
        latest, contents = release(firmware=b"not an ESP image")
        with open(os.path.join(self.firmware_dir, "firmware.bin"), "wb") as f:
            f.write(b"\xe9existing image")
        with open(os.path.join(self.firmware_dir, "BUILD"), "wb") as f:
            f.write(b"29")

        with patch("firmware_releases.urllib.request.urlopen",
                   side_effect=self.mocked_opener([latest], contents)):
            result = self.updater.refresh("0.0.11", "29")

        self.assertFalse(result["ok"])
        self.assertIn("valid ESP32 app image", result["error"])
        with open(os.path.join(self.firmware_dir, "firmware.bin"), "rb") as f:
            self.assertEqual(f.read(), b"\xe9existing image")
        with open(os.path.join(self.firmware_dir, "BUILD"), "rb") as f:
            self.assertEqual(f.read(), b"29")

    def test_rejects_asset_url_outside_official_release_path(self):
        latest, contents = release()
        latest["assets"][0]["browser_download_url"] = (
            "https://attacker.example/firmware.bin")

        with patch("firmware_releases.urllib.request.urlopen",
                   side_effect=self.mocked_opener([latest], contents)):
            result = self.updater.refresh("0.0.11", "29")

        self.assertFalse(result["ok"])
        self.assertIn("asset URL is invalid", result["error"])
        self.assertFalse(os.path.exists(
            os.path.join(self.firmware_dir, "firmware.bin")))

    def test_rejects_malformed_github_digest(self):
        latest, contents = release()
        latest["assets"][0]["digest"] = "sha256:not-a-digest"

        with patch("firmware_releases.urllib.request.urlopen",
                   side_effect=self.mocked_opener([latest], contents)):
            result = self.updater.refresh("0.0.11", "29")

        self.assertFalse(result["ok"])
        self.assertIn("digest mismatch", result["error"])

    def test_rejects_downgraded_asset_redirect(self):
        latest, contents = release()
        opener = self.mocked_opener([latest], contents)

        def downgrade_metadata_redirect(request, timeout):
            response = opener(request, timeout)
            if request.full_url.endswith("/VERSION"):
                return FakeResponse(
                    contents["VERSION"],
                    "http://github.com/CJ8664/folioframe/releases/download/"
                    "folioframe-v0.0.12/VERSION",
                )
            return response

        with patch("firmware_releases.urllib.request.urlopen",
                   side_effect=downgrade_metadata_redirect):
            result = self.updater.refresh("0.0.11", "29")

        self.assertFalse(result["ok"])
        self.assertIn("unexpected host", result["error"])

    def test_rejects_version_metadata_that_does_not_match_release_tag(self):
        latest, contents = release()
        set_asset_contents(latest, contents, "VERSION", b"0.0.11")

        with patch("firmware_releases.urllib.request.urlopen",
                   side_effect=self.mocked_opener([latest], contents)):
            result = self.updater.refresh("0.0.11", "29")

        self.assertFalse(result["ok"])
        self.assertIn("VERSION does not match", result["error"])
        self.assertFalse(os.path.exists(
            os.path.join(self.firmware_dir, "firmware.bin")))

    def test_rejects_build_outside_uint32_range(self):
        latest, contents = release(build="4294967296")
        set_asset_contents(
            latest, contents, "BUILD", b"4294967296")

        with patch("firmware_releases.urllib.request.urlopen",
                   side_effect=self.mocked_opener([latest], contents)):
            result = self.updater.refresh("0.0.11", "29")

        self.assertFalse(result["ok"])
        self.assertIn("exceeds the firmware counter range", result["error"])

    def test_rejects_firmware_smaller_than_minimum_size(self):
        latest, contents = release()
        too_small = b"\xe9" + bytes(10)
        set_asset_contents(latest, contents, "firmware.bin", too_small)
        set_asset_contents(
            latest, contents, "firmware-0.0.12.bin", too_small)

        with patch("firmware_releases.urllib.request.urlopen",
                   side_effect=self.mocked_opener([latest], contents)):
            result = self.updater.refresh("0.0.11", "29")

        self.assertFalse(result["ok"])
        self.assertIn("minimum size", result["error"])

    def test_failed_download_preserves_existing_firmware(self):
        latest, contents = release()
        existing = b"\xe9current firmware"
        with open(os.path.join(self.firmware_dir, "firmware.bin"), "wb") as f:
            f.write(existing)

        opener = self.mocked_opener([latest], contents)

        def fail_firmware_download(request, timeout):
            if request.full_url.endswith("/firmware.bin"):
                raise OSError("simulated download failure")
            return opener(request, timeout)

        with patch("firmware_releases.urllib.request.urlopen",
                   side_effect=fail_firmware_download):
            result = self.updater.refresh("0.0.11", "29")

        self.assertFalse(result["ok"])
        self.assertIn("simulated download failure", result["error"])
        with open(os.path.join(self.firmware_dir, "firmware.bin"), "rb") as f:
            self.assertEqual(f.read(), existing)

    def test_does_not_downgrade_a_newer_local_build(self):
        latest, contents = release("0.0.10", "20", b"\xe9old firmware")
        with patch("firmware_releases.urllib.request.urlopen",
                   side_effect=self.mocked_opener([latest], contents)):
            result = self.updater.refresh("0.0.11", "29")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "local_ahead")
        self.assertFalse(result["updated"])
        self.assertFalse(os.path.exists(
            os.path.join(self.firmware_dir, "firmware.bin")))


if __name__ == "__main__":
    unittest.main()
