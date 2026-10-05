"""Device registry: pairing, claim codes, device tokens.

Security model (docs/SYSTEM_PLAN.md section 3):
  - device_id ("sf-" + lowercase MAC) is a username, NOT a secret.
  - The device token (256-bit, server-generated at claim time) is the secret.
    Only its SHA-256 hash is stored; the plaintext exists server-side only
    between claim approval and the device's first successful claim poll,
    then is wiped.
  - Claim codes: 8 chars from an unambiguous alphabet (~43 bits entropy),
    10-minute TTL, single-use, constant-time comparison, rate-limited by the
    HTTP layer.
  - ONE DEVICE <-> ONE USER, strictly: claiming an already-paired device
    fails with AlreadyPaired unless the current owner unpaired it first.
    Re-claiming after unpair/factory-reset transfers ownership atomically:
    the old token is revoked at the same moment the new one is issued, so
    there is never a moment with two owners.
"""
import hashlib
import hmac
import re
import secrets
import time

DEVICE_ID_RE = re.compile(r"^sf-[0-9a-f]{12}$")
CLAIM_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L
CLAIM_TTL = 600  # seconds
RATE_LIMIT = 5          # attempts
RATE_WINDOW = 60        # seconds


class AlreadyPaired(Exception):
    pass


class BadClaim(Exception):
    pass


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _sanitize_heartbeat(info):
    """Clamp device-reported telemetry to sane types/ranges.

    info comes from the device (POST /v1/device/status), so every value
    is untrusted. Returns a dict of clean values; garbage fields are
    dropped individually without affecting the others.
    """
    out = {}
    for key, lo, hi in (("battery_mv", 0, 6000), ("battery_pct", 0, 100),
                        ("rssi", -120, 0)):
        if info.get(key) is None:
            continue
        try:
            out[key] = max(lo, min(hi, int(info[key])))
        except (TypeError, ValueError):
            continue
    if info.get("fw") is not None:
        out["fw"] = str(info["fw"])[:32]
    return out


class RateLimiter:
    """In-memory sliding-window limiter keyed by client IP."""

    def __init__(self, limit=RATE_LIMIT, window=RATE_WINDOW):
        self.limit = limit
        self.window = window
        self.hits = {}

    def check(self, key):
        now = time.time()
        recent = [t for t in self.hits.get(key, []) if now - t < self.window]
        if len(recent) >= self.limit:
            return False
        recent.append(now)
        self.hits[key] = recent
        return True


class DeviceRegistry:
    def __init__(self, store):
        self.store = store

    # ---- internal ------------------------------------------------------
    def _get(self, device_id):
        return self.store.get("devices", device_id)

    def _put(self, dev):
        self.store.put("devices", dev["device_id"], dev)

    @staticmethod
    def _new_code():
        raw = "".join(secrets.choice(CLAIM_ALPHABET) for _ in range(8))
        return f"{raw[:4]}-{raw[4:]}"

    # ---- pairing -------------------------------------------------------
    def register(self, device_id, panel="", fw=""):
        """Unauthenticated. (Re)starts the claim flow for a device.

        If the device is already paired, the old token stays valid until a
        new claim completes -- ownership transfer requires physical access
        (reading the new code off the device screen), exactly like a
        Chromecast factory reset.
        """
        if not DEVICE_ID_RE.match(device_id or ""):
            raise ValueError("bad device_id")
        dev = self._get(device_id) or {
            "device_id": device_id, "owner": None, "token_hash": None,
            "name": device_id,
        }
        # panel/fw come from the device: keep them short plain strings so
        # a rogue device can't stash markup that renders in the console.
        dev.update({"panel": str(panel or "")[:32], "fw": str(fw or "")[:32],
                    "last_register": int(time.time())})
        dev["claim_code"] = self._new_code()
        dev["claim_expires"] = int(time.time()) + CLAIM_TTL
        dev["claim_used"] = False
        dev.pop("pending_token", None)
        self._put(dev)
        return {"claim_code": dev["claim_code"],
                "expires_in": CLAIM_TTL}

    def _valid_claim_code(self, dev, code):
        if not dev or not code:
            return False
        pending = dev.get("claim_code")
        if not pending or dev.get("claim_used"):
            return False
        if time.time() > dev.get("claim_expires", 0):
            return False
        return hmac.compare_digest(pending, code.strip().upper())

    def poll_claim(self, device_id, code):
        """Device polling. Returns dict; token delivered exactly once."""
        dev = self._get(device_id)
        if not self._valid_claim_code(dev, code):
            raise BadClaim("no pending claim")
        pending_token = dev.pop("pending_token", None)
        if pending_token:
            dev["claim_used"] = True
            dev["claim_code"] = None
            self._put(dev)
            return {"status": "claimed", "device_token": pending_token,
                    "device_id": device_id}
        return {"status": "pending"}

    def claim_by_code(self, code, user_sub):
        """Human claims whatever device holds this pending code."""
        code = (code or "").strip().upper()
        for dev in self.store.all("devices").values():
            if self._valid_claim_code(dev, code):
                return self.claim(dev["device_id"], code, user_sub)
        raise BadClaim("no pending claim")

    def claim(self, device_id, code, user_sub):
        """Human (signed-in) claims the device. Enforces one-device-one-user."""
        dev = self._get(device_id)
        if not self._valid_claim_code(dev, code):
            raise BadClaim("no pending claim")
        if dev.get("owner") and dev["owner"] != user_sub:
            raise AlreadyPaired("device is paired to another account; "
                                "ask the owner to unpair it first")
        token = secrets.token_urlsafe(32)  # 256 bits
        dev["owner"] = user_sub
        dev["token_hash"] = hash_token(token)
        dev["pending_token"] = token  # wiped on first successful poll_claim
        dev["paired_at"] = int(time.time())
        self._put(dev)
        return {"device_id": device_id, "name": dev.get("name", device_id)}

    # ---- device auth ---------------------------------------------------
    def verify_token(self, token):
        """Bearer token -> device dict, or None. Constant-time per device."""
        if not token:
            return None
        digest = hash_token(token)
        for dev in self.store.all("devices").values():
            if dev.get("token_hash") and hmac.compare_digest(
                    dev["token_hash"], digest):
                return dev
        return None

    # ---- management ----------------------------------------------------
    def unpair(self, device_id, user_sub):
        """Owner removes the device. Token revoked immediately."""
        dev = self._get(device_id)
        if not dev or dev.get("owner") != user_sub:
            return False
        dev["owner"] = None
        dev["token_hash"] = None
        dev.pop("pending_token", None)
        dev["claim_code"] = None
        dev["claim_used"] = True
        self._put(dev)
        return True

    def device_self_unpair(self, device_id):
        """Authenticated device wipes its own pairing (factory reset)."""
        dev = self._get(device_id)
        if not dev:
            return False
        dev["owner"] = None
        dev["token_hash"] = None
        dev.pop("pending_token", None)
        # Also invalidate any pending claim code so a stale code shown on
        # the screen can't be claimed after the reset.
        dev["claim_code"] = None
        dev["claim_used"] = True
        self._put(dev)
        return True

    def rename(self, device_id, user_sub, name):
        dev = self._get(device_id)
        if not dev or dev.get("owner") != user_sub:
            return False
        dev["name"] = (name or "")[:40] or device_id
        self._put(dev)
        return True

    def heartbeat(self, device_id, info):
        dev = self._get(device_id)
        if not dev:
            return False
        dev["last_seen"] = int(time.time())
        # These values come from the device, so clamp them to sane
        # types/ranges at ingestion: a rogue device must not be able to
        # store HTML/JS blobs that later render in the web console.
        # Each field is independent: garbage in one never drops the others.
        dev.update(_sanitize_heartbeat(info))
        self._put(dev)
        return True

    def user_devices(self, user_sub):
        return [d for d in self.store.all("devices").values()
                if d.get("owner") == user_sub]

    # ---- pinned override (force push) ----------------------------------
    def set_override_etag(self, device_id, user_sub, etag):
        """Pin a frame for this device. Frame bytes live on disk
        (data/devices/<id>/override.frame); only the etag is in the record."""
        dev = self._get(device_id)
        if not dev or dev.get("owner") != user_sub:
            return False
        dev["override_etag"] = etag
        self._put(dev)
        return True

    def clear_override(self, device_id, user_sub):
        dev = self._get(device_id)
        if not dev or dev.get("owner") != user_sub:
            return False
        dev.pop("override_etag", None)
        self._put(dev)
        return True
