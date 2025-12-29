"""
Redis-backed token bucket implementation with pluggable configuration.

Configuration guidelines:
- Set `refill_rate` to the target average rate (tokens per second),
  e.g. 30 requests/minute -> `0.5`.
- `capacity` defines burst size; keep it at the window budget to cap bursts
  (e.g. `30`), or increase (e.g. `60`) to tolerate short spikes.
- The hard limit over time is governed by `refill_rate`; `capacity` only
  controls how far ahead burst traffic can consume.
"""

from __future__ import annotations

import asyncio
import time
import inspect
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Tuple, Union

from loguru import logger

from .config import custom_config

try:
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover
    Redis = None  # type: ignore


_LUA_SCRIPT = """
local tokens_key = KEYS[1]
local timestamp_key = KEYS[2]

local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local stored_tokens = redis.call('GET', tokens_key)
local tokens = stored_tokens and tonumber(stored_tokens) or capacity

local stored_ts = redis.call('GET', timestamp_key)
local last_ts = stored_ts and tonumber(stored_ts) or now

local delta = now - last_ts
if delta < 0 then
    delta = 0
end

if delta > 0 and refill_rate > 0 then
    local refill = delta * refill_rate
    tokens = math.min(capacity, tokens + refill)
end

local allowed = 0
if tokens >= requested then
    allowed = 1
    tokens = tokens - requested
end

redis.call('SET', tokens_key, tokens)
redis.call('SET', timestamp_key, now)

return {allowed, tokens}
"""


@dataclass(frozen=True)
class TokenBucketConfig:
    """Validated token bucket parameters."""

    capacity: float
    refill_rate: float  # tokens per second
    capacity_key: str = "capacity"
    refill_rate_key: str = "refill_rate"

    @staticmethod
    def from_dict(
        data: Mapping[str, Any],
        *,
        capacity_key: str = "capacity",
        refill_rate_key: str = "refill_rate",
    ) -> "TokenBucketConfig":
        try:
            capacity_raw = data[capacity_key]
            refill_raw = data[refill_rate_key]
        except KeyError as exc:
            raise ValueError(f"Missing token bucket parameter: {exc.args[0]}") from exc

        try:
            capacity = float(capacity_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid capacity value: {capacity_raw}") from exc

        try:
            refill_rate = float(refill_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid refill_rate value: {refill_raw}") from exc

        if capacity <= 0:
            raise ValueError(f"capacity must be > 0 (got {capacity})")
        if refill_rate <= 0:
            raise ValueError(f"refill_rate must be > 0 (got {refill_rate})")

        return TokenBucketConfig(
            capacity=capacity,
            refill_rate=refill_rate,
            capacity_key=capacity_key,
            refill_rate_key=refill_rate_key,
        )


@dataclass(frozen=True)
class TokenBucketState:
    """Current state snapshot of a token bucket."""

    remaining_tokens: float
    capacity: float
    refill_rate: float


class TokenBucket:
    """
    Redis-backed token bucket using pluggable configuration sources.

    Responsibilities:
    - Pull `{capacity, refill_rate}` from a caller-provided loader.
    - Store bucket state under keys prefixed by service code in Redis.
    - Perform atomic refill & consume via a Lua script.
    """

    def __init__(
        self,
        label: str,
        *,
        config: Optional[Mapping[str, Any]] = None,
        config_loader: Optional[Callable[[str], Any]] = None,
        redis_client: Optional[Redis] = None,
        capacity_key: str = "capacity",
        refill_rate_key: str = "refill_rate",
        key_builder: Optional[Callable[[str], Tuple[str, str]]] = None,
        now: Optional[callable] = None,
    ) -> None:
        if Redis is None and redis_client is None:  # pragma: no cover
            raise RuntimeError("redis.asyncio package is required for TokenBucket")

        self.label = label or "default"

        if config is not None and config_loader is not None:
            raise ValueError("Provide either 'config' or 'config_loader', not both.")
        if config is None and config_loader is None:
            raise ValueError("TokenBucket requires a configuration mapping or loader.")

        if config is not None:
            self._config_loader: Callable[[str], Any] = lambda _label: config
        else:
            self._config_loader = config_loader  # type: ignore[assignment]

        if redis_client is None:
            from .storage.redis import get_cache_client

            redis_label = custom_config.get_redis_major_label()
            redis_client = get_cache_client(redis_label)

        self._redis_client: Redis = redis_client  # type: ignore[assignment]
        self._clock = now or time.time

        svc_code = custom_config.get_service_code()
        if key_builder is None:
            hash_tag = f"{{{self.label}}}"
            prefix = f"{svc_code}:tb:{hash_tag}"
            tokens_key = f"{prefix}:tokens"
            timestamp_key = f"{prefix}:ts"
        else:
            tokens_key, timestamp_key = key_builder(self.label)

        self._tokens_key = tokens_key
        self._timestamp_key = timestamp_key

        self._capacity_key = capacity_key
        self._refill_rate_key = refill_rate_key
        self._config_lock = asyncio.Lock()
        self._config: Optional[TokenBucketConfig] = None

    async def acquire(self, tokens: float = 1) -> bool:
        """
        Try to consume `tokens` from the bucket.

        Returns True when enough tokens were available.

        Common setups:
        - Strict 30 req/min: `capacity=30`, `refill_rate=0.5`, `tokens=1`.
        - Allow temporary 2x burst: `capacity=60`, `refill_rate=0.5`.
        - For multi-token actions, pass the required amount via `tokens`.
        """
        if tokens <= 0:
            raise ValueError("tokens must be > 0")

        config = await self._get_config()
        now = float(self._clock())

        try:
            allowed, _remaining = await self._run_script(config, tokens, now)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(
                "Token bucket acquire failed: label={} tokens={} error={}",
                self.label,
                tokens,
                exc,
            )
            return False

        return bool(allowed)

    async def get_state(self) -> TokenBucketState:
        """Return current bucket snapshot (refills to 'now')."""
        config = await self._get_config()
        now = float(self._clock())

        try:
            _, remaining = await self._run_script(config, 0, now)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Token bucket get_state failed: label={} error={}", self.label, exc)
            raise

        return TokenBucketState(
            remaining_tokens=remaining,
            capacity=config.capacity,
            refill_rate=config.refill_rate,
        )

    async def refresh_config(self) -> TokenBucketConfig:
        """Force reload of configuration."""
        async with self._config_lock:
            config = await self._load_config()
            self._config = config
            return config

    def invalidate_config(self) -> None:
        """Invalidate cached configuration so it is reloaded on next access."""
        self._config = None

    async def _get_config(self) -> TokenBucketConfig:
        config = self._config
        if config is not None:
            return config
        async with self._config_lock:
            if self._config is not None:
                return self._config

            config = await self._load_config()
            self._config = config
            return config

    async def _load_config(self) -> TokenBucketConfig:
        raw_config = self._config_loader(self.label)

        if inspect.isawaitable(raw_config):
            raw_config = await raw_config

        if isinstance(raw_config, TokenBucketConfig):
            return raw_config
        if isinstance(raw_config, Mapping):
            return TokenBucketConfig.from_dict(
                raw_config,
                capacity_key=self._capacity_key,
                refill_rate_key=self._refill_rate_key,
            )
        raise TypeError(
            "TokenBucket config loader must return a mapping or TokenBucketConfig instance."
        )

    async def _run_script(
        self,
        config: TokenBucketConfig,
        tokens: float,
        now: float,
    ) -> tuple[int, float]:
        result = await self._redis_client.eval(
            _LUA_SCRIPT,
            2,
            self._tokens_key,
            self._timestamp_key,
            config.capacity,
            config.refill_rate,
            now,
            tokens,
        )

        if not isinstance(result, (list, tuple)) or len(result) != 2:
            raise ValueError(f"Unexpected Lua response: {result}")

        allowed_raw, remaining_raw = result
        allowed = int(float(allowed_raw))
        remaining = float(remaining_raw)
        return allowed, remaining
