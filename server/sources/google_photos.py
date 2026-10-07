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
from token_store import FileTokenStore

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
# The Picker API lives on its own host -- NOT photoslibrary.googleapis.com
# (the restricted Library API). Using the wrong host makes every session
# call fail; verified against the official Picker docs 2026-10-04.
PICKER_BASE = "https://photospicker.googleapis.com/v1"
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
    """Minimal OAuth2 auth-code flow (stdlib only).

    client_provider: optional callable returning (client_id, client_secret).
    When given, credentials are resolved at call time so they can be set or
    rotated at runtime (e.g. by the in-console setup wizard) without
    reconstructing this object. Otherwise the constructor values are used.
    """

    def __init__(self, client_id="", client_secret="", redirect_uri="",
                 token_path="", http=_http, token_store=None,
                 client_provider=None):
        # Credentials normally come straight from the server config
        # (shared service OAuth client). client_provider remains as an
        # escape hatch for tests that resolve credentials dynamically.
        if client_provider is not None:
            self._client_provider = client_provider
        else:
            self._client_provider = lambda: (client_id, client_secret)
        self.redirect_uri = redirect_uri
        self.token_path = token_path
        self._http = http
        self._token_store = token_store or FileTokenStore(token_path)
        self._tokens = None

    def _cid(self):
        cid, _ = self._client_provider()
        return cid

    def _csecret(self):
        _, csecret = self._client_provider()
        return csecret

    # -- authorization -------------------------------------------------
    def auth_url(self, state, redirect_uri=None):
        q = urllib.parse.urlencode({
            "client_id": self._cid(),
            "redirect_uri": redirect_uri or self.redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",   # get a refresh token
            "prompt": "consent",        # force refresh token re-issue
            # Incremental authorization: sign-in happened earlier via GIS;
            # keep any previously granted scopes on this grant.
            "include_granted_scopes": "true",
            "state": state,
        })
        return AUTH_URL + "?" + q

    def exchange_code(self, code, redirect_uri=None):
        body = urllib.parse.urlencode({
            "code": code,
            "client_id": self._cid(),
            "client_secret": self._csecret(),
            "redirect_uri": redirect_uri or self.redirect_uri,
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
        self._token_store.save(tokens)
        self._tokens = tokens

    def _load(self):
        if self._tokens is None:
            self._tokens = self._token_store.load()
        return self._tokens

    @property
    def connected(self):
        t = self._load()
        return bool(t and t.get("refresh_token"))

    def disconnect(self):
        self._tokens = None
        self._token_store.clear()

    def access_token(self):
        t = self._load()
        if not t:
            raise RuntimeError("not connected")
        if t.get("expires_at", 0) > time.time():
            return t["access_token"]
        # refresh
        body = urllib.parse.urlencode({
            "refresh_token": t["refresh_token"],
            "client_id": self._cid(),
            "client_secret": self._csecret(),
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


def _is_transient_network_error(e):
    """True for DNS, connection, and timeout errors (retryable)."""
    import socket
    if isinstance(e, urllib.error.URLError):
        # URLError wraps socket.gaierror (DNS), ConnectionError, TimeoutError
        reason = e.reason
        return isinstance(reason, (socket.gaierror, socket.herror,
                                   ConnectionError, TimeoutError,
                                   socket.timeout))
    return isinstance(e, (ConnectionError, TimeoutError, socket.timeout,
                          socket.gaierror, socket.herror))


def _http_with_retry(http_fn, max_attempts=4):
    """Wrap an _http-style fn with retry for transient network errors."""
    def wrapper(method, url, headers=None, data=None):
        last = None
        for attempt in range(max_attempts):
            try:
                return http_fn(method, url, headers=headers, data=data)
            except Exception as e:
                last = e
                if not _is_transient_network_error(e):
                    raise
                if attempt < max_attempts - 1:
                    time.sleep(min(2.0 * (attempt + 1), 8.0))
        raise last
    return wrapper


class PickerClient:
    """Thin wrapper over the Photos Picker API."""

    def __init__(self, oauth, http=_http):
        self.oauth = oauth
        # Retry transient DNS/network failures (Docker DNS can blip)
        self._http = _http_with_retry(http)

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

    def __init__(self, client, cache_dir, max_items=100, blob_store=None,
                 blob_prefix="gphotos/"):
        self.client = client
        self.cache_dir = cache_dir
        self.max_items = max_items
        self.blob_store = blob_store
        self.blob_prefix = blob_prefix
        if blob_store is None:
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
        # Google's Picker API is eventually consistent: mediaItemsSet may be
        # true before list returns the items. Retry with backoff.
        resp = None
        for attempt in range(12):
            resp = self.client.list_media_items(session_id, None)
            if resp.get("mediaItems"):
                break
            sleep(min(2.0 * (attempt + 1), 10.0))
        first = True
        try:
            while count < self.max_items:
                # First iteration reuses the page from the retry above;
                # subsequent iterations fetch the next page.
                if not first:
                    resp = self.client.list_media_items(session_id,
                                                        page_token)
                first = False
                for item in resp.get("mediaItems", []):
                    if count >= self.max_items:
                        break
                    # Picker API nests file details under item["mediaFile"]:
                    # {id, createTime, type, mediaFile: {baseUrl, mimeType,
                    #  filename, mediaFileMetadata}}. Top-level baseUrl/
                    # mimeType do not exist.
                    mf = item.get("mediaFile") or {}
                    mt = mf.get("mimeType", "")
                    # Only skip when mimeType is explicitly non-image
                    # (e.g. video/*); empty means unknown, try anyway.
                    if mt and not mt.startswith("image/"):
                        continue  # photo frame: images only
                    base_url = mf.get("baseUrl")
                    if not base_url:
                        continue
                    data = self.client.download(base_url)
                    ext = ".jpg" if "jpeg" in mt else ".png"
                    name = item["id"] + ext
                    # Capture metadata for display rendering (date, filename,
                    # dimensions). Stored as JSON sidecar alongside the image.
                    mf_meta = mf.get("mediaFileMetadata") or {}
                    photo_meta = mf_meta.get("photoMetadata") or {}
                    metadata = {
                        "id": item["id"],
                        "createTime": item.get("createTime"),
                        "filename": mf.get("filename"),
                        "mimeType": mt or "image/jpeg",
                        "width": mf_meta.get("width"),
                        "height": mf_meta.get("height"),
                        "cameraMake": mf_meta.get("cameraMake"),
                        "cameraModel": mf_meta.get("cameraModel"),
                        "focalLength": photo_meta.get("focalLength"),
                        "aperture": photo_meta.get("apertureFNumber"),
                        "iso": photo_meta.get("isoEquivalent"),
                        "exposureTime": photo_meta.get("exposureTime"),
                        # Note: location/GPS is NOT available via Picker API.
                        # Google strips location metadata from downloads
                        # for privacy. Album info is also not available
                        # (picker selects individual items, not albums).
                        "source": "google_photos",
                        "downloadedAt": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
                    meta_json = json.dumps(metadata).encode()
                    meta_name = item["id"] + ".meta.json"
                    if self.blob_store is not None:
                        self.blob_store.put(self.blob_prefix + name, data,
                                            mt or "image/jpeg")
                        self.blob_store.put(self.blob_prefix + meta_name,
                                            meta_json, "application/json")
                    else:
                        with open(os.path.join(self.cache_dir, name),
                                  "wb") as f:
                            f.write(data)
                        with open(os.path.join(self.cache_dir, meta_name),
                                  "wb") as f:
                            f.write(meta_json)
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
        # Server injects a BlobStore here for Cloud Run deployments where
        # local disk is ephemeral; otherwise the plain cache dir is used.
        self.blob_store = cfg.get("blob_store")
        # Honor the caller's prefix (the per-user "users/{sub}/gphotos/"
        # the pick flow writes to); default keeps local/test behavior.
        self.blob_prefix = cfg.get("blob_prefix", "gphotos/")
        self.cache_dir = cfg.get("cache_dir", default_cache_dir())
        if self.blob_store is None:
            os.makedirs(self.cache_dir, exist_ok=True)
        self.rng = random.Random()

    def _ids(self):
        if self.blob_store is not None:
            return sorted(k.split("/")[-1]
                          for k in self.blob_store.list(self.blob_prefix)
                          if k.lower().endswith((".jpg", ".jpeg", ".png")))
        return sorted(f for f in os.listdir(self.cache_dir)
                      if f.lower().endswith((".jpg", ".jpeg", ".png")))

    def next_id(self, history):
        return pick_unseen(self._ids(), history, self.rng)

    def get_metadata(self, item_id):
        """Return metadata dict for a photo, or None if not found."""
        # item_id is like "ABC123.jpg"; metadata is "ABC123.meta.json"
        base = item_id.rsplit(".", 1)[0]
        meta_name = base + ".meta.json"
        try:
            if self.blob_store is not None:
                data = self.blob_store.get(self.blob_prefix + meta_name)
                if data is None:
                    return None
                return json.loads(data)
            else:
                path = os.path.join(self.cache_dir, meta_name)
                if not os.path.exists(path):
                    return None
                with open(path) as f:
                    return json.load(f)
        except Exception:
            return None

    def load(self, item_id):
        if self.blob_store is not None:
            data = self.blob_store.get(self.blob_prefix + item_id)
            if data is None:
                raise FileNotFoundError(item_id)
            img = Image.open(BytesIO(data))
        else:
            with open(os.path.join(self.cache_dir, item_id), "rb") as f:
                img = Image.open(f)
                img.load()
                return img.convert("RGB")
        img.load()
        return img.convert("RGB")

    def save(self, item_id, data):
        """Replace a cached photo's bytes (e.g. after a user edit in the
        photo picker). Writes to the same location load() reads from, so
        the frame picks the edited photo up on its next rotation."""
        if self.blob_store is not None:
            self.blob_store.put(self.blob_prefix + item_id, data,
                                "image/jpeg")
        else:
            with open(os.path.join(self.cache_dir, item_id), "wb") as f:
                f.write(data)

    def describe(self):
        d = super().describe()
        d.update(cached=len(self._ids()))
        return d


class GPhotosController:
    """Owns OAuth + picker state + photo source for ONE user's account.

    Shared-service-OAuth model: the OAuth client ID/secret belong to the
    service (admin-configured once); tokens are stored per user, and the
    photo cache is namespaced per user (blob prefix / cache dir).
    """

    def __init__(self, port, http=_http, token_store=None,
                 blob_store=None, blob_prefix="gphotos/", cache_dir=None,
                 public_url=None, client_id="", client_secret="",
                 client_provider=None,
                 store=None, states_key="gphotos_oauth_states"):
        self.redirect_uri = ((public_url.rstrip("/") if public_url
                              else f"http://localhost:{port}")
                             + "/api/gphotos/callback")
        if client_provider is not None:
            provider = client_provider
        else:
            provider = lambda: (client_id, client_secret)
        self._client_provider = provider
        self.oauth = GoogleOAuth(
            redirect_uri=self.redirect_uri, token_path="", http=http,
            token_store=token_store, client_provider=self._client_provider)
        self.blob_store = blob_store
        self.blob_prefix = blob_prefix
        self.cache_dir = cache_dir or default_cache_dir()
        self._http = http
        # OAuth states: persisted in the store when available so the
        # callback survives a restart / lands on another Cloud Run
        # instance; in-memory otherwise (tests, minimal setups).
        self._state_store = store
        self._states_key = states_key
        self._mem_states = {} if store is None else None
        self.pick_state = None  # {session_id, picker_uri, status, count, error}
        self.source = GooglePhotosSource({
            "blob_store": blob_store,
            "blob_prefix": blob_prefix,
            "cache_dir": self.cache_dir,
        })

    @property
    def configured(self):
        cid, csec = self._client_provider()
        return bool(cid and csec)

    # -- oauth states --------------------------------------------------
    def _load_states(self):
        if self._mem_states is not None:
            return dict(self._mem_states)
        return dict(self._state_store.get("_service", self._states_key) or {})

    def _save_states(self, states):
        now = time.time()
        states = {s: i for s, i in states.items()
                  if now - i.get("ts", 0) < 600}
        if self._mem_states is not None:
            self._mem_states = states
        else:
            self._state_store.put("_service", self._states_key, states)

    def new_state(self, redirect_uri):
        """Create an OAuth state bound to the exact redirect URI used."""
        s = secrets.token_urlsafe(16)
        states = self._load_states()
        states[s] = {"ts": time.time(), "redirect_uri": redirect_uri}
        self._save_states(states)
        return s

    def pop_state(self, s):
        """Consume a state; returns its redirect URI, or None if invalid."""
        states = self._load_states()
        info = states.pop(s, None)
        self._save_states(states)
        if not info or time.time() - info.get("ts", 0) >= 600:
            return None
        return info.get("redirect_uri")

    def cache_count(self):
        if self.blob_store is not None:
            return len(self.blob_store.list(self.blob_prefix))
        d = self.cache_dir
        if not os.path.isdir(d):
            return 0
        return len([f for f in os.listdir(d)
                    if f.lower().endswith((".jpg", ".jpeg", ".png"))])
