"""Request latency instrumentation (NFR-01).

The requirement is "response time within a few seconds". The build spec makes it
measurable: stream where possible, batch classification on login, cache by email
id, *instrument every route with a timer, expose p95 over the last 100 requests
at /api/metrics (auth required)*. The batching (one classify call per inbox load)
and the cache (orchestrator/cache.py) already exist. This module is the timer;
backend/routes/metrics.py reports what it collects.

**On NFR-03, because a reader will wonder.** NFR-03 says the backend is
stateless and keeps no email data between calls, so a module that deliberately
remembers past requests needs to say what it remembers. It is a fixed-length
ring of ``(route key, duration)`` pairs: a Flask *url rule* such as
``"GET /api/inbox/<email_id>"`` and a float. No body, subject, sender,
recipient, transcript or email id is stored, and none can be -- a *concrete*
path is never recorded, only the parameterised rule that matched it (see
``route_key``, which is the function NFR-03 hangs on here). The ring is process
memory, bounded by ``config.metrics_window``, never written to disk, and gone on
restart. That is latency metadata about the server, not data about anyone's mail.

Two things are deliberately kept out of the window, both so the figures stay
meaningful rather than to make them look better:

* **/api/metrics itself.** A dashboard polling it every few seconds would fill a
  100-sample window with its own requests and evict the latencies the window
  exists to report -- the endpoint that reports the measurement must not be
  allowed to dominate it. Every route that serves the product is timed.
* **CORS preflight (OPTIONS).** A preflight does no work and the browser sends
  one per cross-origin call, so recording them would halve the effective window
  and drag the overall percentiles toward zero. The auth guard skips OPTIONS for
  the same class of reason.

``/api/healthz`` *is* recorded, because nothing polls it in this project. If a
deployment ever adds a liveness probe on a timer, this is the place to
reconsider -- the exclusion above is about polling, not about importance.
"""

import math
import re
import threading
import time
from collections import deque

from flask import current_app, g, request

# Endpoint names (Flask's "blueprint.function" form) that are timed but not
# recorded. See the module docstring for why the reporting endpoint excludes
# itself. Kept as an explicit set, like jwt.PUBLIC_ENDPOINTS, so widening it is
# a visible act rather than a condition buried in a hook.
EXCLUDED_ENDPOINTS = frozenset({"metrics.metrics"})

# The single bucket every request that matched no rule aggregates under.
UNMATCHED_ROUTE = "<unmatched>"

# Where the window is stashed on the app. app.config is where this codebase
# already keeps per-app objects (APP_CONFIG), so it is where a reader will look.
WINDOW_KEY = "LATENCY_WINDOW"

# The name the start time is stashed under on `g`. Prefixed because `g` is
# shared with every other request-scoped value in the app.
_START_ATTR = "_nfr01_started_at"

# Below this many samples, the nearest-rank p95 *is* the maximum and tells you
# nothing the maximum does not: ceil(0.95 * n) == n for every n < 20, so the
# "95th percentile" of 19 samples is the 19th of 19. At n = 20 it first becomes
# the 19th of 20 and starts to mean something. So this is not a matter of taste,
# it is the arithmetic, and every block of the report says whether it is met.
P95_MIN_SAMPLES = 20

# "<path:email_id>" -> "<email_id>". The converter is a routing detail, and the
# spec names the rule as "/api/inbox/<email_id>".
_CONVERTER = re.compile(r"<(?:[^<>:]+:)?([^<>]+)>")


def route_key(req):
    """The aggregation key for a request: method plus the *rule* that matched.

    NFR-03 depends on this function and nothing else. ``request.path`` for a
    reading-pane fetch is ``/api/inbox/c8f21a04-work-001@northgate.com.au`` -- a
    message id, which in a real mailbox routinely contains the sender's domain
    and sometimes their address. ``request.url_rule.rule`` is
    ``/api/inbox/<path:email_id>``, which is the same information a route
    listing already publishes. Only the rule is ever recorded.

    A request that matched no rule has no rule to record, and falling back to the
    path would reintroduce exactly what the paragraph above forbids, since a
    caller can put anything in a URL. Those aggregate under one constant key.
    """
    rule = getattr(req.url_rule, "rule", None)
    if not rule:
        return UNMATCHED_ROUTE
    return f"{req.method} {_CONVERTER.sub(r'<\1>', rule)}"


def percentile(ordered, fraction):
    """Nearest-rank percentile of an already-sorted, non-empty sequence.

    Nearest-rank rather than linear interpolation, for two reasons. It always
    returns a latency that actually happened: an interpolated p95 is a number no
    request ever took, which is awkward to defend in a report about response
    time. And it is defined for a single sample, where ``statistics.quantiles``
    needs at least two and would have to be special-cased on a window that
    starts empty and fills one request at a time.

    The rank is ``ceil(fraction * n)``, 1-based. For n = 100 the p95 is the 95th
    smallest of the 100 samples; for n = 20 it is the 19th of 20. Both are
    hand-checkable, which is the point -- see tests/test_metrics.py.
    """
    index = math.ceil(fraction * len(ordered)) - 1
    return ordered[max(0, min(index, len(ordered) - 1))]


class LatencyWindow:
    """A bounded, thread-safe ring of recent request durations.

    ``deque(maxlen=N)`` is the whole storage design: appending the N+1th sample
    drops the oldest in O(1), and memory never grows past N small tuples, so a
    server that has been up for a week holds exactly as much as one that has
    served 100 requests.

    Locked because the Flask dev server is threaded, as is any real WSGI server.
    CPython's GIL happens to make a lone ``deque.append`` atomic, but that is an
    implementation detail rather than a promise, and the snapshot the metrics
    route takes is several operations rather than one. An uncontended lock costs
    well under a microsecond per request, against a target measured in seconds.
    """

    def __init__(self, maxlen):
        # A window of zero or fewer samples would make deque(maxlen=0) silently
        # discard everything and the endpoint report an empty window forever,
        # which reads as "nothing was slow" rather than "nothing was measured".
        self.maxlen = max(1, int(maxlen))
        self._samples = deque(maxlen=self.maxlen)
        self._lock = threading.Lock()

    def record(self, key, seconds):
        with self._lock:
            self._samples.append((key, seconds))

    def snapshot(self):
        """A plain list copy, so the report is computed off the lock."""
        with self._lock:
            return list(self._samples)

    def clear(self):
        with self._lock:
            self._samples.clear()

    def __len__(self):
        with self._lock:
            return len(self._samples)


def _ms(seconds):
    """Seconds to milliseconds, keeping sub-millisecond requests non-zero.

    Rounded to 0.1 ms this reported 0.0 for anything faster than 50
    microseconds, which /api/healthz routinely is. That is a false zero in a
    latency report -- and it made test_real_requests_are_recorded flaky, since
    it asserts the recorded durations are positive: the test failed or passed
    depending on how fast the machine was.

    Three decimals is microsecond resolution, which perf_counter genuinely
    provides. The extra digits are noise on a slow request and the difference
    between a number and a wrong number on a fast one.
    """
    return round(seconds * 1000, 3)


def _block(durations, target_seconds):
    """The percentile summary for one set of durations, in milliseconds.

    The empty case returns nulls, not zeros. A zero p95 is a figure that reads
    as "every request was instant"; ``null`` with ``count: 0`` cannot be
    misread, and it is what the endpoint returns before the first request.
    """
    if not durations:
        return {
            "count": 0,
            "p50_ms": None,
            "p95_ms": None,
            "max_ms": None,
            "over_target": 0,
            "enough_for_p95": False,
        }
    ordered = sorted(durations)
    return {
        # `count` is on every block on purpose. A p95 over three samples is
        # meaningless, and a response that reported the figure without the
        # sample size would let it be quoted as though it were not.
        "count": len(ordered),
        "p50_ms": _ms(percentile(ordered, 0.50)),
        "p95_ms": _ms(percentile(ordered, 0.95)),
        "max_ms": _ms(ordered[-1]),
        "over_target": sum(1 for seconds in ordered if seconds > target_seconds),
        "enough_for_p95": len(ordered) >= P95_MIN_SAMPLES,
    }


def latency_report(window, target_seconds):
    """The /api/metrics payload for a window.

    p50 uses the same nearest-rank rule as p95, which makes it the *lower*
    median for an even sample count. That is deliberate: one stated method for
    every figure in the response is easier to defend than a response that mixes
    nearest-rank with the averaged median and says so nowhere.
    """
    samples = window.snapshot()

    by_route = {}
    for key, seconds in samples:
        by_route.setdefault(key, []).append(seconds)

    overall = _block([seconds for _, seconds in samples], target_seconds)
    p95_ms = overall["p95_ms"]

    return {
        "window_size": window.maxlen,
        "units": "milliseconds",
        "percentile_method": "nearest-rank",
        "p95_min_samples": P95_MIN_SAMPLES,
        "target_seconds": target_seconds,
        # The headline NFR-01 answer, or null when nothing has been measured --
        # never `true` by default, which would be a pass nobody earned.
        "p95_within_target": None if p95_ms is None else p95_ms <= target_seconds * 1000,
        "overall": overall,
        "routes": {key: _block(d, target_seconds) for key, d in sorted(by_route.items())},
    }


def get_window():
    """The window installed on the current app, or None if it is not installed."""
    return current_app.config.get(WINDOW_KEY)


def install(app):
    """Attach the timer to the app and return the window it records into.

    Installed *before* the auth guard in the application factory so the clock
    starts before authentication runs: a 401 took real time and belongs in the
    figures. Flask runs ``before_request`` hooks in registration order and runs
    every ``after_request`` hook even when a ``before_request`` short-circuited
    the request, so a rejected call is still timed end to end.
    """
    window = LatencyWindow(app.config["APP_CONFIG"].metrics_window)
    app.config[WINDOW_KEY] = window

    def _record():
        started = g.pop(_START_ATTR, None)
        if started is None:
            return
        elapsed = time.perf_counter() - started
        if request.method == "OPTIONS" or request.endpoint in EXCLUDED_ENDPOINTS:
            return
        window.record(route_key(request), elapsed)

    @app.before_request
    def _start_clock():
        # perf_counter, not time(): it is monotonic and high resolution, and a
        # wall clock adjusted mid-request would otherwise produce a negative
        # duration.
        setattr(g, _START_ATTR, time.perf_counter())
        return None

    @app.after_request
    def _record_response(response):
        _record()
        return response

    @app.teardown_request
    def _record_exception(_exc):
        # after_request does not run when an exception escapes the view -- Flask
        # goes straight to teardown, and app.testing makes that the normal path.
        # Without this, the one class of request most worth measuring, the one
        # that broke, would be the only one missing. _record pops the start
        # time, so a request already recorded above is not counted twice.
        _record()

    return window
