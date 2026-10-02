"""Google Photos source via the Picker API.

Since Google's March 2025 API changes this is the ONLY sanctioned way for a
third-party app to read a user's existing photos: the Library API can now
only see media the app itself created.

Flow:
  1. One-time setup: Google Cloud project + OAuth client (docs/GOOGLE_PHOTOS.md)
  2. User clicks "Connect" -> Google consent -> tokens stored locally (0600)
  3. User clicks "Pick photos" -> picker session -> pickerUri shown
  4. User selects photos in Google's UI (phone or desktop)
  5. Server polls per pollingConfig -> downloads originals into a local cache
  6. Frame rotation runs from the local cache (unseen-first), fully offline

This is a manual-pick flow, NOT a live album sync — Google offers no API
for the latter anymore. Documented honestly in docs/GOOGLE_PHOTOS.md.
"""
import json
import os
import random
import secrets
import time
import urllib.parse
import urllib.request
from io import BytesIO

from PIL import Image

from . import Source, pick_unseen, register

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PICKER_BASE = "https://photoslibrary.googleapis.com/v1"
SCOPE = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"


def _http(method, url, headers=None, data=None):
    """Default transport. Returns (status, body_bytes)."""
    req = urllib.request.Request(url, data=data, headers=headers or {},
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _parse_duration(s):
    """Google duration strings like '2s', '1.5s' -> seconds float."""
    s = (s or "0s").strip()
    if s.endswith("s"):
        s = s[:-1]
    try:
        return float(s)
    except ValueError:
        return 0.0


def default_cache_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "data", "gphotos")


class GoogleOAuth:
    """Minimal OAuth2 auth-code flow (stdlib only)."""

    def __init__(self, client_id, client_secret, redirect_uri, token_path,
                 http=_http):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.token_path = token_path
        self._http = http
        self._tokens = None

    # -- authorization -------------------------------------------------
    def auth_url(self, state):
        q = urllib.parse.urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",   # get a refresh token
            "prompt": "consent",        # force refresh token re-issue
            "state": state,
        })
        return AUTH_URL + "?" + q

    def exchange_code(self, code):
        body = urllib.parse.urlencode({
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }).encode()
        status, raw = self._http(
            "POST", TOKEN_URL,
            {"Content-Type": "application/x-www-form-urlencoded"}, body)
        if status != 200:
            raise RuntimeError(f"token exchange failed: {status} {raw[:200]}")
        self._store(json.loads(raw))
        return self._tokens

    # -- tokens ---------------------------------------------------------
    def _store(self, tokens):
        tokens["expires_at"] = time.time() + tokens.get("expires_in", 3600) - 60
        d = os.path.dirname(self.token_path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(self.token_path, "w") as f:
            json.dump(tokens, f)
        os.chmod(self.token_path, 0o600)
        self._tokens = tokens

    def _load(self):
        if self._tokens is None and os.path.exists(self.token_path):
            with open(self.token_path) as f:
                self._tokens = json.load(f)
        return self._tokens

    @property
    def connected(self):
        t = self._load()
        return bool(t and t.get("refresh_token"))

    def disconnect(self):
        self._tokens = None
        if os.path.exists(self.token_path):
            os.remove(self.token_path)

    def access_token(self):
        t = self._load()
        if not t:
            raise RuntimeError("not connected")
        if t.get("expires_at", 0) > time.time():
            return t["access_token"]
        # refresh
        body = urllib.parse.urlencode({
            "refresh_token": t["refresh_token"],
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
        }).encode()
        status, raw = self._http(
            "POST", TOKEN_URL,
            {"Content-Type": "application/x-www-form-urlencoded"}, body)
        if status != 200:
            raise RuntimeError(f"token refresh failed: {status} {raw[:200]}")
        new = json.loads(raw)
        if "refresh_token" not in new:  # Google often omits it on refresh
            new["refresh_token"] = t["refresh_token"]
        self._store(new)
        return self._tokens["access_token"]


class PickerClient:
    """Thin wrapper over the Photos Picker API."""

    def __init__(self, oauth, http=_http):
        self.oauth = oauth
        self._http = http

    def _auth(self):
        return {"Authorization": "Bearer " + self.oauth.access_token()}

    def _get(self, path, params=None):
        url = PICKER_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        status, raw = self._http("GET", url, self._auth())
        if status != 200:
            raise RuntimeError(f"picker GET {path}: {status} {raw[:200]}")
        return json.loads(raw)

    def _post(self, path, payload=None):
        body = json.dumps(payload or {}).encode()
        status, raw = self._http(
            "POST", PICKER_BASE + path, dict(self._auth(),
                                             **{"Content-Type": "application/json"}),
            body)
        if status != 200:
            raise RuntimeError(f"picker POST {path}: {status} {raw[:200]}")
        return json.loads(raw) if raw else {}

    def _delete(self, path):
        status, raw = self._http("DELETE", PICKER_BASE + path, self._auth())
        if status not in (200, 204):
            raise RuntimeError(f"picker DELETE {path}: {status} {raw[:200]}")

    # -- sessions --------------------------------------------------------
    def create_session(self):
        return self._post("/sessions")

    def get_session(self, session_id):
        return self._get(f"/sessions/{session_id}")

    def delete_session(self, session_id):
        self._delete(f"/sessions/{session_id}")

    def list_media_items(self, session_id, page_token=None, page_size=100):
        params = {"sessionId": session_id, "pageSize": page_size}
        if page_token:
            params["pageToken"] = page_token
        return self._get("/mediaItems", params)

    def download(self, base_url, size="=d"):
        """Download bytes. '=d' = original; '=w1600' = resized."""
        status, raw = self._http("GET", base_url + size, self._auth())
        if status != 200:
            raise RuntimeError(f"download failed: {status}")
        return raw


class PickFlow:
    """Runs the poll -> list -> download -> cleanup sequence."""

    def __init__(self, client, cache_dir, max_items=100):
        self.client = client
        self.cache_dir = cache_dir
        self.max_items = max_items
        os.makedirs(cache_dir, exist_ok=True)

    def run(self, session_id, poll=None):
        """Poll until mediaItemsSet (or timeout), import, delete session.

        poll: optional callable(seconds) replacing time.sleep (for tests).
        Returns the number of imported photos.
        """
        sleep = poll or time.sleep
        deadline = time.time() + 600
        interval = 2.0
        while True:
            s = self.client.get_session(session_id)
            if s.get("mediaItemsSet"):
                break
            pc = s.get("pollingConfig", {})
            interval = _parse_duration(pc.get("pollInterval", "2s")) or 2.0
            timeout = _parse_duration(pc.get("timeoutIn", "600s")) or 600
            deadline = min(deadline, time.time() + timeout)
            if time.time() >= deadline:
                raise TimeoutError("picker session timed out")
            sleep(interval)
        count = 0
        page_token = None
        try:
            while count < self.max_items:
                resp = self.client.list_media_items(session_id, page_token)
                for item in resp.get("mediaItems", []):
                    if count >= self.max_items:
                        break
                    if not item.get("mimeType", "").startswith("image/"):
                        continue  # photo frame: images only
                    data = self.client.download(item["baseUrl"])
                    ext = ".jpg" if "jpeg" in item["mimeType"] else ".png"
                    with open(os.path.join(self.cache_dir,
                                           item["id"] + ext), "wb") as f:
                        f.write(data)
                    count += 1
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
        finally:
            try:
                self.client.delete_session(session_id)
            except Exception:
                pass
        return count


@register
class GooglePhotosSource(Source):
    name = "google_photos"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.cache_dir = cfg.get("cache_dir", default_cache_dir())
        os.makedirs(self.cache_dir, exist_ok=True)
        self.rng = random.Random()

    def _ids(self):
        return sorted(f for f in os.listdir(self.cache_dir)
                      if f.lower().endswith((".jpg", ".jpeg", ".png")))

    def next_id(self, history):
        return pick_unseen(self._ids(), history, self.rng)

    def load(self, item_id):
        with open(os.path.join(self.cache_dir, item_id), "rb") as f:
            img = Image.open(f)
            img.load()
        return img.convert("RGB")

    def describe(self):
        d = super().describe()
        d.update(cached=len(self._ids()))
        return d


class GPhotosController:
    """Owns OAuth + picker state for the server (one user's account)."""

    def __init__(self, cfg, port, http=_http):
        g = cfg.get("google_photos", {})
        here = os.path.dirname(os.path.abspath(__file__))
        token_path = os.path.join(here, "..", ".gphotos_token.json")
        self.oauth = GoogleOAuth(
            g.get("client_id", ""), g.get("client_secret", ""),
            f"http://localhost:{port}/api/gphotos/callback",
            token_path, http)
        self._http = http
        self._states = {}  # oauth state -> timestamp
        self.pick_state = None  # {session_id, picker_uri, status, count, error}

    @property
    def configured(self):
        return bool(self.oauth.client_id and self.oauth.client_secret)

    def new_state(self):
        s = secrets.token_urlsafe(16)
        self._states[s] = time.time()
        return s

    def valid_state(self, s):
        ts = self._states.pop(s, None)
        return ts is not None and time.time() - ts < 600

    def cache_count(self):
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "data", "gphotos")
        if not os.path.isdir(d):
            return 0
        return len([f for f in os.listdir(d)
                    if f.lower().endswith((".jpg", ".jpeg", ".png"))])
