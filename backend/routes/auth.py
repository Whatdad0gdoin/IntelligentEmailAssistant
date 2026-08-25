"""Authentication route (NFR-04).

POST /api/auth/login  ->  { "token": "...", "expires_in": 3600 }
"""

from flask import Blueprint, current_app, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from backend.middleware.jwt import issue_token

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# A real hash of a value nobody knows, used to equalise response timing when the
# email does not exist. Without it, a missing user returns measurably faster
# than a wrong password, which leaks account existence just as surely as a
# different error message would.
_TIMING_DECOY = generate_password_hash("timing-equalisation-decoy")

# Deliberately identical for "unknown email" and "wrong password": no user
# enumeration (spec section 3).
_INVALID = "Invalid email or password"


@bp.post("/login")
def login():
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""

    if not email or not password:
        return jsonify({"error": _INVALID}), 401

    config = current_app.config["APP_CONFIG"]
    stored_hash = config.auth_users.get(email)

    # Always run a hash comparison so both branches cost the same.
    if stored_hash is None:
        check_password_hash(_TIMING_DECOY, password)
        return jsonify({"error": _INVALID}), 401

    if not check_password_hash(stored_hash, password):
        return jsonify({"error": _INVALID}), 401

    token, expires_in = issue_token(email, config)
    return jsonify({"token": token, "expires_in": expires_in}), 200
