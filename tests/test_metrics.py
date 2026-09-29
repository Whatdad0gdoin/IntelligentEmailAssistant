"""NFR-01: every route is timed, and /api/metrics reports the window.

Three groups, in the order a reader should read them:

- **The percentile maths**, checked against input sets small enough to work out
  by hand. "It returns a number" is not a test of a percentile; every expected
  value below was computed from the nearest-rank rule on paper first, so a change
  to the method fails here instead of quietly changing the reported figure.
- **The instrumentation**, exercised over real HTTP through the real application
  factory, including a route that sleeps for a known time so the test can tell a
  timer apart from a constant.
- **NFR-03**, which is the one that matters most in this file: a parameterised
  route must aggregate under its *rule*, and a real fixture email id must never
  appear in the response. That test asserts both halves -- that the id is absent
  *and* that the request was recorded under the rule -- because the absence of an
  id in a response that recorded nothing at all would prove nothing.

The window is per app, so each test's `app` fixture starts empty. The one sample
that arrives unbidden is the login the `token` fixture performs, which is why
several tests clear the window first and say so.
"""

import re
import threading
import time

import pytest

from backend.app import create_app
from backend.middleware.jwt import PUBLIC_ENDPOINTS
from backend.middleware.timing import (
    P95_MIN_SAMPLES,
    UNMATCHED_ROUTE,
    WINDOW_KEY,
    LatencyWindow,
    latency_report,
    percentile,
)
from tests.conftest import TEST_EMAIL, TEST_PASSWORD, WORK_EMAIL_ID


def _window(app):
    return app.config[WINDOW_KEY]


def _report(client, headers):
    response = client.get("/api/metrics", headers=headers)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _login(http):
    response = http.post(
        "/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.get_json()
    return {"Authorization": f"Bearer {response.get_json()['token']}"}


# --- The percentile maths --------------------------------------------------


def test_percentile_is_nearest_rank_on_hand_checked_sets():
    """Rank = ceil(fraction * n), 1-based, so p95 of 100 is the 95th smallest."""
    hundred = [i / 1000 for i in range(1, 101)]          # 1ms .. 100ms
    assert percentile(hundred, 0.50) == pytest.approx(0.050)
    assert percentile(hundred, 0.95) == pytest.approx(0.095)

    twenty = [i / 100 for i in range(1, 21)]             # 10ms .. 200ms
    # ceil(0.95 * 20) = 19 -> the 19th of 20, which is 0.19 and NOT the max.
    assert percentile(twenty, 0.95) == pytest.approx(0.19)
    assert percentile(twenty, 0.50) == pytest.approx(0.10)

    nineteen = [i / 100 for i in range(1, 20)]           # 10ms .. 190ms
    # ceil(0.95 * 19) = 19 -> the 19th of 19, i.e. the max. This is exactly why
    # P95_MIN_SAMPLES is 20 and not a round number someone liked.
    assert percentile(nineteen, 0.95) == pytest.approx(0.19) == max(nineteen)

    assert percentile([0.42], 0.95) == pytest.approx(0.42)


def test_p95_min_samples_is_the_point_where_p95_stops_being_the_max():
    """The constant is derived, so derive it again rather than trusting it."""
    for n in range(1, P95_MIN_SAMPLES):
        ordered = [i / 1000 for i in range(1, n + 1)]
        assert percentile(ordered, 0.95) == max(ordered), n
    ordered = [i / 1000 for i in range(1, P95_MIN_SAMPLES + 1)]
    assert percentile(ordered, 0.95) < max(ordered)


def test_percentile_never_interpolates():
    """Every figure reported is a latency some request actually took."""
    for n in (1, 2, 3, 7, 19, 20, 100):
        ordered = [i / 7 for i in range(1, n + 1)]
        for fraction in (0.5, 0.9, 0.95, 0.99):
            assert percentile(ordered, fraction) in ordered, (n, fraction)


def test_report_figures_are_hand_checked():
    window = LatencyWindow(100)
    # Inserted descending, so a report that forgot to sort would fail here.
    for i in reversed(range(1, 101)):
        window.record("GET /api/thing", i / 1000)

    report = latency_report(window, target_seconds=5)

    assert report["overall"] == {
        "count": 100,
        "p50_ms": 50.0,      # 50th smallest of 100
        "p95_ms": 95.0,      # 95th smallest of 100
        "max_ms": 100.0,
        "over_target": 0,
        "enough_for_p95": True,
    }
    assert report["routes"]["GET /api/thing"] == report["overall"]
    assert report["p95_within_target"] is True
    assert report["percentile_method"] == "nearest-rank"
    assert report["window_size"] == 100


def test_over_target_counts_requests_above_the_target_only():
    """At the target is not over it, and the target comes from config."""
    window = LatencyWindow(100)
    for seconds in (4.9, 5.0, 5.1, 6.0):
        window.record("GET /api/slow-thing", seconds)

    report = latency_report(window, target_seconds=5)

    assert report["overall"]["over_target"] == 2          # 5.1 and 6.0
    assert report["overall"]["p50_ms"] == 5000.0          # ceil(0.5*4)=2 -> 2nd
    assert report["overall"]["p95_ms"] == 6000.0          # ceil(0.95*4)=4 -> 4th
    assert report["p95_within_target"] is False


def test_a_small_sample_is_marked_as_one():
    """A p95 over three samples must not be quotable as though it were not."""
    window = LatencyWindow(100)
    for seconds in (0.1, 0.2, 0.3):
        window.record("GET /api/thing", seconds)

    block = latency_report(window, target_seconds=5)["overall"]

    assert block["count"] == 3
    assert block["enough_for_p95"] is False
    # And the figure it offers is simply the maximum, as the flag implies.
    assert block["p95_ms"] == block["max_ms"] == 300.0


def test_per_route_counts_are_reported_separately():
    window = LatencyWindow(100)
    for _ in range(3):
        window.record("GET /api/inbox", 1.0)
    window.record("POST /api/summarise", 2.0)

    report = latency_report(window, target_seconds=5)

    assert report["overall"]["count"] == 4
    assert report["routes"]["GET /api/inbox"]["count"] == 3
    assert report["routes"]["POST /api/summarise"]["count"] == 1
    assert report["routes"]["POST /api/summarise"]["max_ms"] == 2000.0


# --- Empty state -----------------------------------------------------------


def test_an_empty_window_reports_nulls_not_zeros():
    """No requests yet must not divide by zero, and must not read as a pass."""
    report = latency_report(LatencyWindow(100), target_seconds=5)

    assert report["overall"] == {
        "count": 0,
        "p50_ms": None,
        "p95_ms": None,
        "max_ms": None,
        "over_target": 0,
        "enough_for_p95": False,
    }
    assert report["routes"] == {}
    # Not `True`: an unmeasured target is not a met one.
    assert report["p95_within_target"] is None


def test_the_endpoint_serves_an_empty_window_without_crashing(app, client, auth_headers):
    """The same thing over HTTP. The window is cleared after the login sample."""
    _window(app).clear()

    report = _report(client, auth_headers)

    assert report["overall"]["count"] == 0
    assert report["overall"]["p95_ms"] is None
    assert report["routes"] == {}


# --- Auth (NFR-04) ---------------------------------------------------------


def test_metrics_requires_a_token(client):
    assert client.get("/api/metrics").status_code == 401


def test_metrics_is_not_on_the_public_allowlist():
    """The spec says auth required, so it must never be allowlisted."""
    assert "metrics.metrics" not in PUBLIC_ENDPOINTS


# --- The instrumentation ---------------------------------------------------


def test_real_requests_are_recorded(app, client, auth_headers):
    """Counts come out right, and the durations are real positive numbers."""
    _window(app).clear()
    for _ in range(4):
        assert client.get("/api/healthz").status_code == 200

    report = _report(client, auth_headers)

    assert report["overall"]["count"] == 4
    assert report["routes"]["GET /api/healthz"]["count"] == 4
    assert report["routes"]["GET /api/healthz"]["max_ms"] > 0
    assert report["overall"]["p50_ms"] > 0


def test_the_login_route_is_instrumented_too(client, auth_headers):
    """auth_headers logs in, so that sample is already in the window."""
    report = _report(client, auth_headers)
    assert report["routes"]["POST /api/auth/login"]["count"] == 1


def test_an_unauthenticated_request_is_still_timed(app, client, auth_headers):
    """Proof the timer is installed before the auth guard: a 401 took time too."""
    _window(app).clear()
    assert client.get("/api/inbox").status_code == 401

    report = _report(client, auth_headers)

    assert report["routes"]["GET /api/inbox"]["count"] == 1


def test_a_slow_route_measures_longer_than_a_fast_one(config):
    """Tells a timer apart from a constant.

    The route sleeps for a known 60ms, so the recorded figure has a floor that a
    hardcoded or zero duration cannot satisfy. The route is registered before the
    first request because Flask 3 refuses to add one afterwards.
    """
    delay = 0.06
    app = create_app(config)
    app.config.update(TESTING=True)

    @app.get("/api/slow-for-test")
    def _slow():
        time.sleep(delay)
        return {"ok": True}, 200

    http = app.test_client()
    headers = _login(http)
    _window(app).clear()

    assert http.get("/api/slow-for-test", headers=headers).status_code == 200
    assert http.get("/api/healthz").status_code == 200

    report = _report(http, headers)
    slow = report["routes"]["GET /api/slow-for-test"]["max_ms"]
    fast = report["routes"]["GET /api/healthz"]["max_ms"]

    # A 10% margin below the sleep: perf_counter cannot under-report a sleep by
    # more than clock resolution, but the margin keeps a loaded CI box honest.
    assert slow >= delay * 1000 * 0.9, report
    assert slow > fast, report


def test_a_preflight_request_is_not_recorded(app, client):
    """A CORS preflight does no work; recording it would dilute every figure."""
    _window(app).clear()
    client.open("/api/inbox", method="OPTIONS")
    assert len(_window(app)) == 0


def test_an_error_response_is_still_timed(app, client, auth_headers, stub_llm):
    """A 404 is a request the user waited for, so it belongs in the figures."""
    _window(app).clear()
    assert client.post(
        "/api/summarise", json={"email_id": "no-such-id"}, headers=auth_headers
    ).status_code == 404

    report = _report(client, auth_headers)

    assert report["routes"]["POST /api/summarise"]["count"] == 1


# --- NFR-03: no email content in the metrics store -------------------------


def test_a_request_that_raises_is_still_timed(config):
    """The teardown path, which exists for the one request most worth measuring.

    Flask skips after_request when an exception escapes the view, so without the
    teardown hook a request that broke would be the only kind missing from the
    figures. app.testing makes exceptions propagate, which is exactly the
    condition being tested.
    """
    app = create_app(config)
    app.config.update(TESTING=True)

    @app.get("/api/explodes-for-test")
    def _boom():
        raise RuntimeError("deliberate failure with no email content in it")

    http = app.test_client()
    headers = _login(http)
    _window(app).clear()

    with pytest.raises(RuntimeError):
        http.get("/api/explodes-for-test", headers=headers)

    samples = _window(app).snapshot()
    assert [key for key, _ in samples] == ["GET /api/explodes-for-test"]


def test_a_request_is_recorded_exactly_once(app, client, auth_headers):
    """after_request and teardown_request both record; neither may double count."""
    _window(app).clear()
    client.get("/api/healthz")
    assert len(_window(app)) == 1


def test_a_real_email_id_never_appears_in_the_metrics_response(app, client, auth_headers):
    """The critical one. Both halves are asserted deliberately.

    Reading a message puts its id in the URL path. If the recorder used
    request.path, that id -- which carries the sender's domain, and in a real
    mailbox often their address -- would be in this response. It must aggregate
    under the rule instead.

    The second assertion is what stops this test passing for the wrong reason: if
    the request had not been recorded at all, the id would also be absent, and a
    green tick would mean nothing.
    """
    _window(app).clear()
    read = client.get(f"/api/inbox/{WORK_EMAIL_ID}", headers=auth_headers)
    assert read.status_code == 200, read.get_json()

    response = client.get("/api/metrics", headers=auth_headers)
    text = response.get_data(as_text=True)

    assert WORK_EMAIL_ID not in text
    for fragment in ("c8f21a04", "work-001", "northgate"):
        assert fragment not in text, fragment

    assert response.get_json()["routes"]["GET /api/inbox/<email_id>"]["count"] == 1


def test_an_unmatched_path_is_not_recorded_verbatim(app, client, auth_headers):
    """A caller can put anything in a URL, including a body fragment.

    An unmatched path has no rule to fall back on, so it must aggregate under one
    constant rather than under itself.
    """
    marker = "ZEBRAFISH-PATH-MARKER"
    _window(app).clear()
    assert client.get(f"/api/{marker}", headers=auth_headers).status_code == 404

    response = client.get("/api/metrics", headers=auth_headers)

    assert marker not in response.get_data(as_text=True)
    assert response.get_json()["routes"][UNMATCHED_ROUTE]["count"] == 1


def test_every_route_key_is_a_rule_the_app_already_publishes(app, client, auth_headers):
    """The general form of the test above, so a route added later is covered.

    Every key in the breakdown is either the unmatched bucket or a method plus a
    rule from the app's own url map. Nothing else can get in, so no concrete path
    can.
    """
    _window(app).clear()
    client.get("/api/healthz")
    client.get(f"/api/inbox/{WORK_EMAIL_ID}", headers=auth_headers)
    client.get("/api/nope", headers=auth_headers)
    client.post("/api/auth/login", json={})

    published = set()
    for rule in app.url_map.iter_rules():
        path = re.sub(r"<(?:[^<>:]+:)?([^<>]+)>", r"<\1>", str(rule))
        for method in rule.methods:
            published.add(f"{method} {path}")

    for key in _report(client, auth_headers)["routes"]:
        assert key == UNMATCHED_ROUTE or key in published, key


def test_the_window_holds_only_route_keys_and_floats(app, client, auth_headers):
    """What is stored, asserted at the store rather than at the response."""
    client.get(f"/api/inbox/{WORK_EMAIL_ID}", headers=auth_headers)

    samples = _window(app).snapshot()

    assert samples, "nothing was recorded, so this test proves nothing"
    for key, seconds in samples:
        assert isinstance(key, str) and isinstance(seconds, float)
        assert WORK_EMAIL_ID not in key


# --- The window is bounded -------------------------------------------------


def test_the_window_drops_the_oldest_samples():
    """150 samples into a window of 100 keeps the last 100, not the first."""
    window = LatencyWindow(100)
    for i in range(1, 151):
        window.record("GET /api/thing", i / 1000)

    samples = window.snapshot()

    assert len(samples) == 100
    durations = [seconds for _, seconds in samples]
    assert min(durations) == pytest.approx(0.051)     # 1..50 fell out
    assert max(durations) == pytest.approx(0.150)


def test_more_requests_than_the_window_does_not_grow_it(config):
    """Over HTTP, with a deliberately tiny window so eviction is observable."""
    config.metrics_window = 5
    app = create_app(config)
    app.config.update(TESTING=True)
    http = app.test_client()

    for _ in range(12):
        assert http.get("/api/healthz").status_code == 200
    headers = _login(http)                      # the 13th recorded request

    report = _report(http, headers)

    assert report["window_size"] == 5
    assert report["overall"]["count"] == 5
    assert len(_window(app)) == 5
    # The last five recorded requests were four healthz calls and the login.
    assert report["routes"]["GET /api/healthz"]["count"] == 4
    assert report["routes"]["POST /api/auth/login"]["count"] == 1


def test_polling_the_endpoint_does_not_evict_the_samples_it_reports(config):
    """Why /api/metrics excludes itself from its own window."""
    config.metrics_window = 5
    app = create_app(config)
    app.config.update(TESTING=True)
    http = app.test_client()
    headers = _login(http)
    _window(app).clear()

    for _ in range(3):
        assert http.get("/api/healthz").status_code == 200
    for _ in range(10):
        assert http.get("/api/metrics", headers=headers).status_code == 200

    report = _report(http, headers)

    assert report["overall"]["count"] == 3
    assert report["routes"]["GET /api/healthz"]["count"] == 3
    assert "GET /api/metrics" not in report["routes"]


def test_a_window_size_of_zero_cannot_silence_the_metrics(config):
    """METRICS_WINDOW=0 would make deque(maxlen=0) discard everything, and the
    endpoint would report an empty window forever -- which reads as "nothing was
    slow" rather than "nothing was measured"."""
    config.metrics_window = 0
    app = create_app(config)
    app.config.update(TESTING=True)
    http = app.test_client()
    headers = _login(http)

    assert _window(app).maxlen >= 1
    assert _report(http, headers)["overall"]["count"] >= 1


# --- Thread safety ---------------------------------------------------------


def test_concurrent_recording_loses_no_samples():
    """The dev server is threaded, so the window is written from many threads.

    Honest about what this proves: under CPython's GIL a bare deque.append would
    probably also survive this, so the test is a regression guard against a store
    that is not safe under threads (an index-juggling ring, a list plus a
    counter), not a proof that the lock is load-bearing today.
    """
    window = LatencyWindow(4000)
    errors = []

    def worker(name):
        try:
            for i in range(250):
                window.record(f"GET /api/{name}", i / 1000)
        except Exception as exc:                        # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(window) == 8 * 250
    report = latency_report(window, target_seconds=5)
    assert report["overall"]["count"] == 2000
    assert len(report["routes"]) == 8
