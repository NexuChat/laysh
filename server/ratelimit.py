from __future__ import annotations

import hashlib
import hmac
import time
from collections import defaultdict, deque
from collections.abc import Callable


class GenerationLimiter:
    """In-memory limits that retain only keyed, day-scoped client hashes."""

    def __init__(
        self,
        *,
        secret: bytes,
        per_ip_per_hour: int,
        global_per_day: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not secret:
            raise ValueError("rate-limit hash secret must not be empty")
        self._secret = secret
        self._per_ip_per_hour = per_ip_per_hour
        self._global_per_day = global_per_day
        self._clock = clock
        self._ip_windows: dict[str, deque[float]] = defaultdict(deque)
        self._global_day: int | None = None
        self._global_count = 0

    def _key(self, client_ip: str, day: int) -> str:
        message = f"{day}:{client_ip}".encode()
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def acquire(self, client_ip: str) -> str | None:
        now = self._clock()
        day = int(now // 86_400)
        if day != self._global_day:
            self._global_day = day
            self._global_count = 0
            self._ip_windows.clear()
        key = self._key(client_ip, day)
        window = self._ip_windows[key]
        while window and window[0] <= now - 3_600:
            window.popleft()
        if len(window) >= self._per_ip_per_hour:
            return "ip_generation_limit"
        if self._global_count >= self._global_per_day:
            return "global_generation_limit"
        window.append(now)
        self._global_count += 1
        return None
