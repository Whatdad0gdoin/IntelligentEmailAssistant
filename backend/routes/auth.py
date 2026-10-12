"""Authentication routes (NFR-04).

POST /api/auth/login   ->  { "token": "...", "expires_in": 3600 }
GET  /api/auth/signup  ->  { "enabled": true, "invite_code_required": false }
POST /api/auth/signup  ->  201 { "token": "...", "expires_in": 3600 }

Accounts come from two places: AUTH_USERS in backend/.env, which a teammate
adds with backend/scripts/add_user.py, and the sign-up page, which writes to
the accounts database (backend/accounts.py). Login checks both.

Sign-up proves nothing about the address: the backend has no way to send a
confirmation email, deliberately (tests/test_draft.py asserts no mail-sending
library exists). That is acceptable because an account here holds no mail of
its own. A new account sees the demo inbox until its owner connects Gmail,
and that step is where Google checks who they are.
"""

import hmac
import re

from flask import Blueprint, current_app, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from backend.accounts import AccountExists, get_store
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

# Loose on purpose: the address is a login name, not a mailbox the app writes
# to, so the check only refuses what cannot be an address at all.
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
MIN_PASSWORD = 8
MAX_PASSWORD = 128


def _stored_hash(config, email):
    """The password hash for this login, from .env first, then sign-ups."""
    if email in config.auth_users:
        return config.auth_users[email]
    return get_store(config).password_hash(email)


@bp.post("/login")
def login():
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""

    if not email or not password:
        return jsonify({"error": _INVALID}), 401

    config = current_app.config["APP_CONFIG"]
    stored_hash = _stored_hash(config, email)

    # Always run a hash comparison so both branches cost the same.
    if stored_hash is None:
        check_password_hash(_TIMING_DECOY, password)
        return jsonify({"error": _INVALID}), 401

    if not check_password_hash(stored_hash, password):
        return jsonify({"error": _INVALID}), 401

    token, expires_in = issue_token(email, config)
    return jsonify({"token": token, "expires_in": expires_in}), 200


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    config = current_app.config["APP_CONFIG"]

    # GET tells the form what to show, before anyone types anything.
    if request.method == "GET":
        return jsonify({
            "enabled": config.signup_enabled,
            "invite_code_required": bool(config.signup_code),
        }), 200

    if not config.signup_enabled:
        return jsonify({"error": "Sign-up is turned off on this server. Ask the team for an account."}), 403

    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    code = (payload.get("invite_code") or "").strip()

    # The invite code is checked before anything about the email, so without
    # a valid code the route says nothing about which addresses have accounts.
    if config.signup_code and not hmac.compare_digest(code.encode(), config.signup_code.encode()):
        return jsonify({"error": "That invite code is not valid."}), 403

    if len(email) > 254 or not _EMAIL.fullmatch(email):
        return jsonify({"error": "Enter an email address like name@example.com."}), 400
    if not isinstance(password, str) or not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        return jsonify({
            "error": f"Choose a password of {MIN_PASSWORD} to {MAX_PASSWORD} characters."
        }), 400

    exists = "An account with this email already exists. Sign in instead."
    if email in config.auth_users:
        return jsonify({"error": exists}), 409
    try:
        get_store(config).create_user(email, generate_password_hash(password))
    except AccountExists:
        return jsonify({"error": exists}), 409

    # Signed straight in: making someone type the password again proves nothing.
    token, expires_in = issue_token(email, config)
    return jsonify({"token": token, "expires_in": expires_in}), 201
