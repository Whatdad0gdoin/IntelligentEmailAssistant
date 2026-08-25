"""In-memory result cache (spec section 4.1: "a re-read costs zero API calls").

What goes in here matters for NFR-03. This cache holds *model output* --
summaries, category labels -- and never an email body. Bodies are fetched from
the source per request, preprocessed in memory, and dropped when the request
ends. The spec allows exactly this: "cache holds summaries only".

Entries are namespaced by the authenticated user. Summaries are keyed on
email_id as the spec says, but a bare email_id would be a cross-account leak
the moment two accounts exist, so the user is part of the key.

Process memory only. Nothing here touches disk, and a restart empties it.
"""

import threading
from collections import OrderedDict

# Enough for several users with a full inbox each; small enough to stay bounded.
DEFAULT_MAX_ENTRIES = 512


class MemoryCache:
    """A small thread-safe LRU.

    Deliberately not Redis or a file: persistence is the one property we do not
    want. If the process dies, model output dies with it.
    """

    def __init__(self, max_entries=DEFAULT_MAX_ENTRIES):
        self.max_entries = max_entries
        self._entries = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _key(user, item_id):
        return (user or "", item_id)

    def get(self, user, item_id):
        with self._lock:
            key = self._key(user, item_id)
            if key in self._entries:
                self._entries.move_to_end(key)
                self.hits += 1
                return self._entries[key]
            self.misses += 1
            return None

    def set(self, user, item_id, value):
        with self._lock:
            key = self._key(user, item_id)
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self, user=None):
        """Drop one user's entries, or everything when user is None."""
        with self._lock:
            if user is None:
                self._entries.clear()
                return
            for key in [k for k in self._entries if k[0] == user]:
                del self._entries[key]

    def stats(self):
        with self._lock:
            return {"entries": len(self._entries), "hits": self.hits, "misses": self.misses}


# Summaries (FR-01) and category labels (FR-02). Separate caches so clearing
# one does not silently discard the other.
SUMMARY_CACHE = MemoryCache()
CLASSIFY_CACHE = MemoryCache()


def clear_all(user=None):
    SUMMARY_CACHE.clear(user)
    CLASSIFY_CACHE.clear(user)
