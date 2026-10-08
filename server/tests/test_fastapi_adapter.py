import asyncio
import json
import threading
import unittest
from types import SimpleNamespace

import spectra_server


def asgi_request(path, method="GET", headers=(), body=b""):
    async def send_request():
        sent = []
        received = False

        async def receive():
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": body,
                        "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        raw_path = path.encode("ascii")
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": raw_path,
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"testserver"), *headers],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
        await spectra_server.app(scope, receive, send)
        return sent

    return asyncio.run(send_request())


class FastAPIAdapterTests(unittest.TestCase):
    def setUp(self):
        self.original_app = spectra_server.APP
        spectra_server.APP = SimpleNamespace(
            firebase_cfg={"web": {}},
            auth=SimpleNamespace(
                client_id="example.apps.googleusercontent.com"),
        )

    def tearDown(self):
        spectra_server.APP = self.original_app

    def test_legacy_route_response_is_adapted(self):
        response = spectra_server._dispatch_legacy_request(
            "GET", "/api/config", [("Host", "testserver")],
            ("127.0.0.1", 12345), b"",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(
            json.loads(response.body),
            {
                "firebase": {},
                "google_client_id": "example.apps.googleusercontent.com",
            },
        )

    def test_unsupported_method_returns_allow_header(self):
        response = spectra_server._dispatch_legacy_request(
            "PUT", "/api/config", [], ("127.0.0.1", 12345), b"",
        )

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.headers["allow"], "GET, POST, PATCH, DELETE")

    def test_fastapi_boundary_preserves_route_and_request_id(self):
        sent = asgi_request(
            "/api/config", headers=[(b"x-request-id", b"test-request-1")])
        start = next(message for message in sent
                     if message["type"] == "http.response.start")
        body = next(message for message in sent
                    if message["type"] == "http.response.body")
        headers = dict(start["headers"])

        self.assertEqual(start["status"], 200)
        self.assertEqual(headers[b"x-request-id"], b"test-request-1")
        self.assertEqual(json.loads(body["body"])["google_client_id"],
                         "example.apps.googleusercontent.com")

    def test_health_endpoint_and_oversized_request(self):
        health = asgi_request("/healthz")
        health_start = next(message for message in health
                            if message["type"] == "http.response.start")
        self.assertEqual(health_start["status"], 200)

        oversized = asgi_request(
            "/api/config",
            headers=[(b"content-length",
                      str(spectra_server.MAX_REQUEST_BYTES + 1).encode())],
        )
        oversized_start = next(message for message in oversized
                               if message["type"] == "http.response.start")
        self.assertEqual(oversized_start["status"], 413)

    def test_lifespan_starts_firmware_refresh_in_background(self):
        refreshed = threading.Event()

        class FakeServer:
            def tick(self):
                pass

            def refresh_firmware_from_releases(self):
                refreshed.set()
                return {"ok": True, "status": "up_to_date"}

        previous_app = spectra_server.APP
        spectra_server.APP = FakeServer()

        async def run_lifespan():
            async with spectra_server.lifespan(spectra_server.app):
                self.assertTrue(refreshed.wait(timeout=1))

        try:
            asyncio.run(run_lifespan())
        finally:
            spectra_server.APP = previous_app


if __name__ == "__main__":
    unittest.main()
