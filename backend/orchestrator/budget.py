"""Per-session request cap (spec section 4.1).

The project has a fixed API budget. The cap that protects it has to live at the
one place every model call passes through, or it is not a cap at all -- which
is why it is enforced inside the orchestrator client rather than at the routes.

A session is one login: the key combines the JWT subject with the token's issue
time, so signing in again starts a fresh allowance while a single long-lived
token cannot spend without limit.

The counter is in-process. It resets on restart and is not shared between
workers, so it is a guard rail against a runaway loop or a stuck retry, not a
billing control. Real spend limits belong in the OpenAI dashboard, and the
report should say so rather than claiming this enforces the dollar figure.
"""

import threading
from collections import OrderedDict


class BudgetExceeded(RuntimeError):
    """The session has used its allowance of model calls."""

    def __init__(self, used, limit):
        super().__init__(
            f"This session has used its allowance of {limit} AI requests. "
            f"Sign in again to start a new session."
        )
        self.used = used
        self.limit = limit


# Bounded so a long-running server does not accumulate a counter per login
# forever. Oldest sessions fall off first.
_MAX_TRACKED_SESSIONS = 1000


class SessionBudget:
    def __init__(self, limit):
        self.limit = limit
        self._counts = OrderedDict()
        self._lock = threading.Lock()

    def spend(self, session_key, cost=1):
        """Record `cost` requests against a session, or raise BudgetExceeded.

        Checked before the call goes out, not after, so an over-budget session
        cannot spend one more request to discover it is over budget.
        """
        if not session_key:
            return 0
        with self._lock:
            used = self._counts.get(session_key, 0)
            if used + cost > self.limit:
                raise BudgetExceeded(used, self.limit)
            self._counts[session_key] = used + cost
            self._counts.move_to_end(session_key)
            while len(self._counts) > _MAX_TRACKED_SESSIONS:
                self._counts.popitem(last=False)
            return used + cost

    def used(self, session_key):
        with self._lock:
            return self._counts.get(session_key, 0)

    def reset(self, session_key=None):
        with self._lock:
            if session_key is None:
                self._counts.clear()
            else:
                self._counts.pop(session_key, None)


_budgets = {}
_lock = threading.Lock()


def get_budget(config):
    """One budget per configured limit, shared across requests."""
    with _lock:
        limit = config.max_requests_per_session
        if limit not in _budgets:
            _budgets[limit] = SessionBudget(limit)
        return _budgets[limit]
