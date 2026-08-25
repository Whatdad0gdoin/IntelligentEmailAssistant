"""Unauthenticated liveness probe.

Deliberately returns no user or email data -- it exists so the frontend dev
proxy and any future deployment check can confirm the API is up without a token.
"""

from flask import Blueprint, jsonify

bp = Blueprint("health", __name__)


@bp.get("/api/healthz")
def healthz():
    return jsonify({"status": "ok"}), 200
