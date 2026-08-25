"""Development entry point.

Loads backend/.env then starts Flask. Production would use a WSGI server
instead; this exists so `python -m backend.run` is all a teammate needs.
"""

import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from backend.app import create_app  # noqa: E402  (must follow load_dotenv)

app = create_app()

if __name__ == "__main__":
    app.run(port=int(os.environ.get("PORT", 5000)), debug=bool(os.environ.get("FLASK_DEBUG")))
