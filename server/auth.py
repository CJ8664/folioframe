"""Human authentication: Google sign-in (server-held OAuth client) + sessions.

Model: the admin configures ONE Google OAuth client for the service
(config "google": {"client_id", "client_secret"} — one-time setup).
Users just click "Sign in with Google"; they never see a client ID,
secret, or the Cloud Console.

Login flow (web console):
  1. Welcome page (public): "Sign in with Google" button (GIS), initialized
     with the server's client ID (served via /api/config).
  2. POST /api/auth/token {id_token} -> server verifies the token
     cryptographically (signature, aud == server client ID, iss, exp,
     email_verified) -- never trusts a decoded-but-unverified JWT.
  3. Server get-or-creates the user record (keyed by Google `sub`) and
     sets an httpOnly+Secure+SameSite=Lax session cookie.

Everything beyond the welcome page requires a session.

The Google `sub` claim is the stable user key. Email allowlist (config
"auth": {"allowlist": [...]}) optionally restricts who may sign in;
empty/missing means anyone with a Google account may create an account --
their data is isolated per user, so an open server leaks nothing across
accounts.
"""
import hashlib
import hmac
import os
import re
import secrets
import time

SESSION_COOKIE = "sf_session"
SESSION_TTL = 24 * 3600  # seconds

# Google OAuth web client IDs look like "<id>.apps.googleusercontent.com".
CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9-]+\.apps\.googleusercontent\.com$")

TRUSTED_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


class AuthError(Exception):
    pass


def _default_verify(id_token_str, client_id):
    """Cryptographically verify a Google ID token. Returns the claims dict.

    Separated for test injection: tests pass their own verifier.
    """
    from google.auth.transport import requests as grequests
    from google.oauth2 import id_token as gid_token
    return gid_token.verify_oauth2_token(
        id_token_str, grequests.Request(), client_id)


class AuthManager:
    def __init__(self, store, config, verify_fn=None):
        self.store = store
        self.cfg = config.get("auth", {})
        self.allowlist = set(self.cfg.get("allowlist", []))
        # The service's own Google OAuth client (admin-configured, one time).
        # Sign-in verifies ID tokens against this client ID; users never
        # supply one.
        self.client_id = config.get("google", {}).get("client_id", "")
        self._verify = verify_fn or _default_verify
        self.secret = self._load_secret()

    def _load_secret(self):
        # Stable across restarts: kept in the store (Firestore on Cloud Run).
        # One-time migration from the legacy local file.
        secret_hex = self.store.get("_service", "session_secret")
        if secret_hex:
            return bytes.fromhex(secret_hex)
        here = os.path.dirname(os.path.abspath(__file__))
        legacy = os.path.join(here, ".session_secret")
        if os.path.exists(legacy):
            with open(legacy, "rb") as f:
                secret = f.read().strip()
        else:
            secret = secrets.token_bytes(32)
        self.store.put("_service", "session_secret", secret.hex())
        return secret

    # ---- ID token verification -----------------------------------------
    def verify_id_token(self, id_token_str):
        """Verify and return (sub, email, name). Raises AuthError.

        The token's audience must equal the server's configured Google
        OAuth client ID. The server holds no per-user OAuth state.
        """
        client_id = self.client_id
        if not client_id or not CLIENT_ID_RE.fullmatch(client_id):
            raise AuthError("server Google sign-in is not configured")
        try:
            info = self._verify(id_token_str, client_id)
        except Exception as e:
            raise AuthError(f"token verification failed: {e}")
        # Defense in depth: assert the security-critical claims explicitly so
        # a verifier swap can't silently drop them.
        if info.get("aud") != client_id:
            raise AuthError("token audience mismatch")
        if info.get("iss") not in TRUSTED_ISSUERS:
            raise AuthError("token issuer not trusted")
        if info.get("exp", 0) < time.time() - 60:
            raise AuthError("token expired")
        sub = info.get("sub")
        email = info.get("email", "")
        if not sub:
            raise AuthError("token has no sub claim")
        if not info.get("email_verified"):
            raise AuthError("email not verified")
        if self.allowlist and email not in self.allowlist:
            raise AuthError("account not on the allowlist")
        return sub, email, info.get("name", "")

    # ---- sessions ------------------------------------------------------
    def _sign(self, session_id):
        return hmac.new(self.secret, session_id.encode(),
                        hashlib.sha256).hexdigest()

    def create_session(self, sub):
        session_id = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        self.store.put("sessions", session_id, {
            "sub": sub, "csrf": csrf,
            "created": int(time.time()),
        })
        user = self.store.get("users", sub) or {}
        self.store.put("users", sub, user)
        return session_id, csrf

    def cookie_value(self, session_id):
        return f"{session_id}.{self._sign(session_id)}"

    def session_from_cookie(self, cookie_header):
        """Return (session_id, session_dict) or (None, None)."""
        if not cookie_header:
            return None, None
        for part in cookie_header.split(";"):
            part = part.strip()
            if not part.startswith(SESSION_COOKIE + "="):
                continue
            value = part[len(SESSION_COOKIE) + 1:]
            if "." not in value:
                return None, None
            session_id, sig = value.rsplit(".", 1)
            if not hmac.compare_digest(sig, self._sign(session_id)):
                return None, None
            sess = self.store.get("sessions", session_id)
            if not sess:
                return None, None
            if time.time() - sess.get("created", 0) > SESSION_TTL:
                self.store.delete("sessions", session_id)
                return None, None
            return session_id, sess
        return None, None

    def destroy_session(self, session_id):
        self.store.delete("sessions", session_id)

    def check_csrf(self, session, provided):
        return bool(provided) and hmac.compare_digest(
            str(provided), str(session.get("csrf", "")))
