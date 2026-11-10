"""Rate limiting (IN-21).

Generic Cell Rate Algorithm (GCRA): for a limit of N requests per period T, each request moves a
"theoretical arrival time" forward by T/N; a request is refused when that time would run more than T
ahead of now. It allows a burst of N, then a steady N per T, with one small value per key and no
fixed-window edge effects (no 2N bursts across a window boundary).

* :class:`RedisRateLimiter`: shared across every API process; the arithmetic runs in one Lua script
  with Redis's own clock, so it is atomic and unaffected by clock differences between servers.
* :class:`MemoryRateLimiter`: the same algorithm in-process, for local development and tests.

Identifiers (emails, addresses, ids) are hashed before they become keys, so no personal data is
stored in Redis. If Redis is unreachable the limiter lets requests through and logs an error:
account lockout and the database still protect sign-in, and a Redis outage must not take the
whole CRM down.
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

import redis

from mixt.core.config import AppConfig, Rate
from mixt.core.logging import get_logger

log = get_logger("mixt.ratelimit")
KEY_PREFIX = "mixt:rl:"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after_seconds: int
    remaining: int


class RateLimiter(Protocol):
    def hit(self, name: str, identity: str, rate: Rate) -> Decision: ...


def key_for(name: str, identity: str) -> str:
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"{KEY_PREFIX}{name}:{digest}"


def _gcra(stored_tat: float | None, now: float, rate: Rate) -> tuple[Decision, float | None]:
    """Pure algorithm (milliseconds). Returns the decision and the new stored value (None = unchanged)."""
    period = rate.period_seconds * 1000.0
    interval = period / rate.count
    tat = max(stored_tat if stored_tat is not None else now, now)
    new_tat = tat + interval
    allow_at = new_tat - period
    if now < allow_at:
        return Decision(False, max(1, math.ceil((allow_at - now) / 1000.0)), 0), None
    remaining = int((period - (new_tat - now)) // interval)
    return Decision(True, 0, max(0, remaining)), new_tat


class MemoryRateLimiter:
    def __init__(self, clock: Any = None) -> None:
        self._clock = clock or (lambda: time.monotonic() * 1000.0)
        self._state: dict[str, tuple[float, float]] = {}  # key -> (tat, expires_at)
        self._lock = threading.Lock()

    def hit(self, name: str, identity: str, rate: Rate) -> Decision:
        key = key_for(name, identity)
        with self._lock:
            now = float(self._clock())
            if len(self._state) > 50_000:
                self._state = {k: v for k, v in self._state.items() if v[1] > now}
            current = self._state.get(key)
            stored = current[0] if current and current[1] > now else None
            decision, new_tat = _gcra(stored, now, rate)
            if new_tat is not None:
                self._state[key] = (new_tat, new_tat)
            return decision

    def reset(self) -> None:
        with self._lock:
            self._state.clear()


_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local interval = tonumber(ARGV[1])
local period = tonumber(ARGV[2])
local tat = tonumber(redis.call('GET', KEYS[1]) or now)
if tat < now then tat = now end
local new_tat = tat + interval
local allow_at = new_tat - period
if now < allow_at then
  return {0, math.ceil((allow_at - now) / 1000), 0}
end
redis.call('SET', KEYS[1], tostring(new_tat), 'PX', math.max(1, math.ceil(new_tat - now)))
return {1, 0, math.floor((period - (new_tat - now)) / interval)}
"""


class RedisRateLimiter:
    def __init__(self, url: str) -> None:
        self._client = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)
        self._script = self._client.register_script(_LUA)
        self._errors = (redis.RedisError, OSError)

    def hit(self, name: str, identity: str, rate: Rate) -> Decision:
        period = rate.period_seconds * 1000.0
        try:
            allowed, retry, remaining = self._script(keys=[key_for(name, identity)], args=[period / rate.count, period])
        except self._errors as exc:
            log.error("rate_limit_backend_unavailable", error=type(exc).__name__)
            return Decision(True, 0, rate.count)
        return Decision(bool(int(allowed)), max(1, int(retry)) if not int(allowed) else 0, int(remaining))

    def ping(self) -> bool:
        try:
            return bool(self._client.ping())
        except self._errors:
            return False


class DisabledRateLimiter:
    def hit(self, name: str, identity: str, rate: Rate) -> Decision:
        return Decision(True, 0, rate.count)


_instances: dict[str, RateLimiter] = {}
_lock = threading.Lock()


def limiter_for(config: AppConfig) -> RateLimiter:
    """One limiter per configuration (cached), chosen from the deployment settings."""
    if not config.rate_limits_enabled:
        return DisabledRateLimiter()
    url = config.redis_url.get_secret_value() if config.redis_url else None
    cache_key = url or "memory"
    with _lock:
        if cache_key not in _instances:
            _instances[cache_key] = RedisRateLimiter(url) if url else MemoryRateLimiter()
        return _instances[cache_key]


def reset_memory_limiters() -> None:
    """Tests: forget all in-process counters."""
    with _lock:
        for limiter in _instances.values():
            if isinstance(limiter, MemoryRateLimiter):
                limiter.reset()
