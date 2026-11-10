"""Retailer login for the deployed dashboard, built on the standard library only.

Off unless ``ECOM_AUTH_USERS`` is set, so local runs and tests behave as before.
Passwords are stored as salted PBKDF2 hashes, never in plain text. A successful
login sets a signed, HttpOnly cookie; every other route then requires it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

PBKDF2_ITERATIONS = 200_000
"""OWASP-range work factor: slow enough to resist guessing, fast enough for a login."""

COOKIE_NAME = "ecom_session"
PUBLIC_PATHS = frozenset({"/login", "/health"})
"""Routes reachable without a login; /health stays open for the host's uptime checks."""


def hash_password(password: str, *, salt: str | None = None) -> str:
    """Return ``pbkdf2_sha256$<iterations>$<salt>$<hash>`` for storing in configuration."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Check a password against a stored hash in constant time."""
    try:
        scheme, iterations, salt, expected = encoded.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
    return hmac.compare_digest(digest.hex(), expected)


def parse_users(spec: str) -> dict[str, str]:
    """Parse ``name=<hash>;name2=<hash>`` into a name -> hash mapping."""
    users = {}
    for entry in filter(None, (part.strip() for part in spec.split(";"))):
        name, _, encoded = entry.partition("=")
        if not name or not encoded:
            raise ValueError("ECOM_AUTH_USERS entries must look like name=<hash>")
        users[name.strip()] = encoded.strip()
    return users


class SessionSigner:
    """Issue and check signed session tokens of the form ``user|expiry|signature``."""

    def __init__(self, secret: str, *, hours: int) -> None:
        self._key = secret.encode()
        self._seconds = hours * 3600

    @property
    def max_age(self) -> int:
        """Cookie lifetime in seconds."""
        return self._seconds

    def issue(self, user: str) -> str:
        payload = f"{user}|{int(time.time()) + self._seconds}"
        return _b64(f"{payload}|{self._sign(payload)}")

    def read(self, token: str | None) -> str | None:
        """Return the user for a valid, unexpired token, else None."""
        if not token:
            return None
        try:
            user, expiry, signature = _unb64(token).rsplit("|", 2)
        except ValueError:
            return None
        if not hmac.compare_digest(signature, self._sign(f"{user}|{expiry}")):
            return None
        return user if int(expiry) > time.time() else None

    def _sign(self, payload: str) -> str:
        return hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()


def install_auth(app: FastAPI, *, users: dict[str, str], signer: SessionSigner) -> None:
    """Require a login for every route except the login page and /health."""

    @app.middleware("http")
    async def require_login(request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        user = signer.read(request.cookies.get(COOKIE_NAME))
        if user is None or user not in users:
            if request.url.path == "/":
                return RedirectResponse("/login", status_code=303)
            return JSONResponse({"detail": "login required"}, status_code=401)
        request.state.user = user
        return await call_next(request)

    @app.get("/login", include_in_schema=False)
    def login_page() -> HTMLResponse:
        return HTMLResponse(_login_html(error=False))

    @app.post("/login", include_in_schema=False)
    async def login(request: Request) -> Response:
        form = parse_qs((await request.body()).decode())
        name = form.get("username", [""])[0]
        password = form.get("password", [""])[0]
        if name not in users or not verify_password(password, users[name]):
            return HTMLResponse(_login_html(error=True), status_code=401)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            COOKIE_NAME,
            signer.issue(name),
            httponly=True,
            samesite="lax",
            secure=_is_https(request),
            max_age=signer.max_age,
        )
        return response

    @app.get("/logout", include_in_schema=False)
    def logout() -> Response:
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(COOKIE_NAME)
        return response

    @app.get("/session", include_in_schema=False)
    def session(request: Request) -> dict[str, str]:
        return {"user": request.state.user}


def _is_https(request: Request) -> bool:
    """True behind an HTTPS proxy (Render terminates TLS and forwards plain HTTP)."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto == "https"


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _unb64(token: str) -> str:
    return base64.urlsafe_b64decode(token.encode()).decode()


def _login_html(*, error: bool) -> str:
    message = '<p class="err">Wrong username or password.</p>' if error else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Retailer login</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin:0; min-height:100vh; display:grid; place-items:center;
         font-family: system-ui, sans-serif; background:#f5f6f8; color:#1f2937; }}
  @media (prefers-color-scheme: dark) {{ body {{ background:#0d0d0d; color:#e5e7eb; }}
    form {{ background:#1a1a1a !important; border-color:#333 !important; }}
    input {{ background:#111; color:#e5e7eb; border-color:#444; }} }}
  form {{ width:min(340px, 90vw); padding:28px; border:1px solid #d1d5db;
          border-radius:10px; background:#fff; display:grid; gap:12px; }}
  h1 {{ font-size:18px; margin:0 0 4px; }}
  label {{ font-size:13px; display:grid; gap:4px; }}
  input {{ padding:9px 10px; border:1px solid #cbd5e1; border-radius:6px; font-size:14px; }}
  button {{ padding:10px; border:0; border-radius:6px; background:#2563eb; color:#fff;
            font-size:14px; cursor:pointer; }}
  .err {{ color:#dc2626; font-size:13px; margin:0; }}
  .note {{ font-size:12px; color:#6b7280; margin:0; }}
</style></head>
<body><form method="post" action="/login">
  <h1>Olist Retail Dashboard</h1>
  <p class="note">Retailer sign-in</p>
  {message}
  <label>Username <input name="username" autocomplete="username" required></label>
  <label>Password
    <input name="password" type="password" autocomplete="current-password" required></label>
  <button type="submit">Sign in</button>
</form></body></html>"""
