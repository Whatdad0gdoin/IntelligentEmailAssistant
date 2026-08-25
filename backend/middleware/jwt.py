"""JWT issuing and the fail-closed auth guard (NFR-04).

Design note: authentication is enforced by a single ``before_request`` hook that
protects *everything* under /api by default, with a small explicit allowlist of
public endpoints. It is deliberately not a per-route decorator.

With decorators, adding a new route and forgetting the decorator silently ships
an unauthenticated endpoint. Here, forgetting to allowlist a route makes it
return 401 -- the failure is visible and safe rather than invisible and unsafe.
"""

import datetime as _dt

import jwt
from flask import current_app, g, jsonify, request

# Endpoint names (Flask's "blueprint.function" form) reachable without a token.
PUBLIC_ENDPOINTS = frozenset({
    "auth.login",
    "health.healthz",
})


class AuthError(Exception):
    def __init__(self, message="Not authenticated", status=401):
        super().__init__(message)
        self.message = message
        self.status = status


def issue_token(subject, config):
    """Return (token, expires_in_seconds) for the given subject."""
    now = _dt.datetime.now(_dt.timezone.utc)
    expires_in = config.jwt_expires_in
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + _dt.timedelta(seconds=expires_in),
    }
    token = jwt.encode(payload, config.jwt_secret, algorithm=config.jwt_algorithm)
    return token, expires_in


def decode_token(token, config):
    """Decode and validate a token, or raise AuthError."""
    try:
        return jwt.decode(token, config.jwt_secret, algorithms=[config.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("Invalid token") from exc


def _extract_bearer():
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError()
    return token.strip()


def install(app):
    """Attach the global auth guard to the app."""

    @app.before_request
    def _require_auth():
        # CORS preflight carries no Authorization header by design.
        if request.method == "OPTIONS":
            return None

        endpoint = request.endpoint

        if endpoint in PUBLIC_ENDPOINTS or endpoint == "static":
            return None

        # Anything under /api requires a token -- including paths that do not
        # resolve to a route. Letting an unmatched /api path fall through to a
        # 404 would tell an unauthenticated caller which endpoints exist, so
        # auth is checked before routing is allowed to matter. Outside /api an
        # unmatched path still 404s normally.
        if endpoint is None and not request.path.startswith("/api"):
            return None

        try:
            claims = decode_token(_extract_bearer(), current_app.config["APP_CONFIG"])
        except AuthError as exc:
            return jsonify({"error": exc.message}), exc.status

        g.user_email = claims.get("sub")
        return None
