"""GET /api/metrics (NFR-01, spec step 10).

The spec: "expose p95 over the last 100 requests at /api/metrics (auth
required)". The measuring is done by backend/middleware/timing.py, which also
explains why an in-process latency window does not violate NFR-03; this route
only shapes what that window already holds.

**Auth.** There is no decorator here and there does not need to be. The
fail-closed guard in middleware/jwt.py protects everything under /api unless the
endpoint is on a two-entry allowlist, and ``metrics.metrics`` is deliberately not
on it. tests/test_auth.py enumerates the url map, so this route was covered by
the 401 test the moment it was registered.

Latency figures are not secret in the way a mailbox is, but they are an
operational profile of the server and the spec asks for auth, so they get it.

The route excludes itself from the window (see EXCLUDED_ENDPOINTS in the timing
module), so polling it cannot evict the samples it is meant to report.
"""

from flask import Blueprint, jsonify

from backend.middleware.timing import get_window, latency_report
from backend.routes.support import config, handle_errors

bp = Blueprint("metrics", __name__, url_prefix="/api")


@bp.get("/metrics")
@handle_errors
def metrics():
    window = get_window()
    if window is None:
        # The application factory installs the timer, so this is unreachable in
        # a correctly built app. It returns an error rather than an empty report
        # because a report of zero samples reads as "nothing has been slow",
        # which is a passing figure nobody measured.
        return jsonify({"error": "Latency instrumentation is not installed."}), 503

    return jsonify(latency_report(window, config().latency_target_seconds)), 200
