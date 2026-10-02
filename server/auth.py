"""Human authentication: Google sign-in + sessions + CSRF.

Login flow (web console):
  1. Browser gets a Google ID token via Google Identity Services (GIS).
  2. POST /api/auth/google {id_token} -> server verifies the token
     cryptographically (signature, aud, iss, exp) -- never trusts a
     decoded-but-unverified JWT.
  3. Server creates a session, sets an httpOnly+Secure+SameSite=Lax cookie.

The Google `sub` claim is the stable user key. Email allowlist (config
"auth": {"allowlist": [...]}) restricts who may sign in; empty/missing
means any Google account (documented, single-user deployments should set it).
"""
import hashlib
import hmac
import os
import secrets
import time

SESSION_COOKIE = "sf_session"
SESSION_TTL = 24 * 3600  # seconds


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
        self.client_id = (self.cfg.get("client_id")
                          or config.get("google_photos", {}).get("client_id", ""))
        self.allowlist = set(self.cfg.get("allowlist", []))
        self._verify = verify_fn or _default_verify
        self.secret = self._load_secret()

    def _load_secret(self):
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, ".session_secret")
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read().strip()
        secret = secrets.token_bytes(32)
        with open(path, "wb") as f:
            f.write(secret)
        os.chmod(path, 0o600)
        return secret

    # ---- Google token verification ------------------------------------
    def verify_google_token(self, id_token_str):
        """Verify and return (sub, email, name). Raises AuthError."""
        if not self.client_id:
            raise AuthError("server has no Google OAuth client_id configured")
        try:
            info = self._verify(id_token_str, self.client_id)
        except Exception as e:
            raise AuthError(f"token verification failed: {e}")
        # Defense in depth: google-auth already checks these, but we assert
        # the security-critical claims explicitly so a verifier swap can't
        # silently drop them.
        if info.get("aud") != self.client_id:
            raise AuthError("token audience mismatch")
        if info.get("iss") not in ("accounts.google.com",
                                   "https://accounts.google.com"):
            raise AuthError("token issuer not Google")
        if info.get("exp", 0) < time.time() - 60:
            raise AuthError("token expired")
        sub = info.get("sub")
        email = info.get("email", "")
        if not sub:
            raise AuthError("token has no sub claim")
        if not info.get("email_verified"):
            raise AuthError("email not verified by Google")
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
