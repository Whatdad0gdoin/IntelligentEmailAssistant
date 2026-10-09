"""Flask application factory.

Three-tier architecture (spec section 1): this layer handles HTTP, auth and
validation only. Every LLM call lives in backend/orchestrator; no route imports
a vendor SDK or knows the model name.
"""

import logging
import os

from flask import Flask, jsonify
from flask_cors import CORS

from backend.config import Config
from backend.middleware import jwt as jwt_middleware
from backend.middleware import logging_filter
from backend.middleware import timing
from backend.routes import ai as ai_routes
from backend.routes import attachments as attachment_routes
from backend.routes import auth as auth_routes
from backend.routes import health as health_routes
from backend.routes import inbox as inbox_routes
from backend.routes import metrics as metrics_routes
from backend.routes import voice as voice_routes


def create_app(config=None):
    app = Flask(__name__)

    # Loaded before anything else so a bad config fails at startup, not mid-session.
    app.config["APP_CONFIG"] = config or Config(require_llm=False)

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    logging_filter.install(app)          # NFR-03 backstop
    # Order matters: the timer is installed before the auth guard so the clock
    # starts before authentication runs. A 401 took real time and belongs in the
    # latency figures.
    timing.install(app)                  # NFR-01 latency window
    jwt_middleware.install(app)          # NFR-04 fail-closed guard

    CORS(
        app,
        origins=app.config["APP_CONFIG"].cors_origins,
        allow_headers=["Authorization", "Content-Type"],
        methods=["GET", "POST", "OPTIONS"],
    )

    app.register_blueprint(health_routes.bp)
    app.register_blueprint(auth_routes.bp)
    app.register_blueprint(inbox_routes.bp)   # FR-08
    app.register_blueprint(attachment_routes.bp)  # FR-08: open one attachment
    app.register_blueprint(ai_routes.bp)      # FR-01, FR-02, FR-03, FR-07
    app.register_blueprint(voice_routes.bp)   # FR-05
    app.register_blueprint(metrics_routes.bp)  # NFR-01

    @app.errorhandler(404)
    def _not_found(_):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def _server_error(_):
        # Never echo the request payload back: it may contain email content (NFR-03).
        return jsonify({"error": "Internal server error"}), 500

    return app


if __name__ == "__main__":
    create_app().run(port=int(os.environ.get("PORT", 5000)), debug=False)
