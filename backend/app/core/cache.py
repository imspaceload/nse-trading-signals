"""
Tiny in-process TTL cache used by the API.

Why: every open browser tab polls the API. Without this, N tabs = N scanner runs /
N Kite quote calls / N NSE scrapes. With it:
  * fresh value            -> returned instantly
  * stale value            -> returned instantly, refreshed once in the background
  * nothing cached yet     -> ONE caller computes it, concurrent callers wait for that result
  * refresh fails          -> the last good value keeps being served (and the error is logged)
"""
import threading
import time
from typing import Any, Callable, Dict, Optional


class _Entry:
    __slots__ = ("value", "at", "refreshing")

    def __init__(self, value: Any, at: float):
        self.value = value
        self.at = at
        self.refreshing = False


class TTLCache:
    def __init__(self, name: str = "cache"):
        self.name = name
        self._entries: Dict[Any, _Entry] = {}
        self._key_locks: Dict[Any, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock_for(self, key: Any) -> threading.Lock:
        with self._guard:
            return self._key_locks.setdefault(key, threading.Lock())

    def get(self, key: Any, ttl: float, compute: Callable[[], Any], stale_ttl: Optional[float] = None) -> Any:
        """
        ttl       — seconds the value is considered fresh.
        stale_ttl — how long an expired value may still be served while it refreshes in the
                    background (default: 10x ttl). Past that, the caller recomputes and waits.
        """
        stale_ttl = stale_ttl if stale_ttl is not None else ttl * 10
        now = time.time()
        entry = self._entries.get(key)

        if entry and now - entry.at < ttl:
            return entry.value

        if entry and now - entry.at < stale_ttl:
            self._refresh_in_background(key, entry, compute)
            return entry.value

        lock = self._lock_for(key)
        with lock:
            # someone else may have filled it while we waited for the lock
            entry = self._entries.get(key)
            if entry and time.time() - entry.at < ttl:
                return entry.value
            try:
                value = compute()
            except Exception:
                if entry:                       # serve the last good value rather than failing
                    print(f"[{self.name}] refresh failed for {key!r}, serving stale value")
                    return entry.value
                raise
            self._entries[key] = _Entry(value, time.time())
            return value

    def _refresh_in_background(self, key: Any, entry: _Entry, compute: Callable[[], Any]) -> None:
        with self._guard:
            if entry.refreshing:
                return
            entry.refreshing = True

        def _run():
            try:
                value = compute()
                self._entries[key] = _Entry(value, time.time())
            except Exception as e:
                print(f"[{self.name}] background refresh failed for {key!r}: {e}")
                entry.refreshing = False

        threading.Thread(target=_run, daemon=True).start()

    def invalidate(self, key: Any = None) -> None:
        """Drop one key (or everything). Use after a write so the next read is fresh."""
        if key is None:
            self._entries.clear()
        else:
            self._entries.pop(key, None)
