"""Tiny in-memory login throttle (per username + client IP). Fine for a single-process prototype."""
import time
from threading import Lock


class LoginThrottle:
    def __init__(self, max_attempts: int, lock_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.lock_seconds = lock_seconds
        self._fails: dict[str, list[float]] = {}
        self._lock = Lock()

    def _prune(self, key: str, now: float) -> list[float]:
        recent = [t for t in self._fails.get(key, []) if now - t < self.lock_seconds]
        self._fails[key] = recent
        return recent

    def retry_after(self, key: str) -> int:
        """Seconds the caller must wait, or 0 if allowed to try."""
        now = time.monotonic()
        with self._lock:
            recent = self._prune(key, now)
            if len(recent) >= self.max_attempts:
                return max(1, int(self.lock_seconds - (now - recent[0])))
            return 0

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._fails.setdefault(key, []).append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)
