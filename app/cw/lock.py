import os
import socket
import uuid
import asyncio
import random
import time
from typing import Optional
from loguru import logger


def default_owner_id() -> str:
    """Generate a default owner id (host:pid:uuid8)."""
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


# Atomically release: only delete if value==owner
_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""

# Atomically extend: only set new TTL (seconds) if value==owner
_EXTEND_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
else
    return 0
end
"""

class LockManager:
    """Distributed lock manager using Redis (async)."""

    def __init__(
        self,
        redis_client,
        lock_prefix: str = "lock",
        default_ttl: int = 300,
        owner: Optional[str] = None,
        fence_prefix: str = "fence",   # <— fencing token counter key prefix
    ):
        """
        Args:
            redis_client: Async Redis client instance
            lock_prefix: Prefix for lock keys, e.g. 'lock'
            default_ttl: Default TTL (seconds)
            owner: Identifier of the lock owner (defaults to host:pid:uuid8)
            fence_prefix: Prefix for per-resource fencing counters, e.g. 'fence'
        """
        self.redis_client = redis_client
        self.lock_prefix = lock_prefix
        self.fence_prefix = fence_prefix
        self.default_ttl = int(default_ttl)
        self.owner = owner or default_owner_id()

        self.lock_key: Optional[str] = None
        self.acquired: bool = False
        self._ttl: int = self.default_ttl

        # fencing token (monotonic increasing number generated when lock is acquired)
        self.fencing_token: Optional[int] = None

        # 自动续期
        self._auto_renew_task: Optional[asyncio.Task] = None
        self._auto_renew_interval: Optional[float] = None
        self._auto_renew_margin: float = 0.2  # TTL 的安全比例（在 80% 处续期）

    def _make_lock_key(self, *parts) -> str:
        return f"{self.lock_prefix}:{':'.join(str(part) for part in parts)}"

    def _make_fence_key(self) -> str:
        assert self.lock_key, "lock_key not set"
        # 1:1 mapping to the resource, independent counter
        return f"{self.fence_prefix}:{self.lock_key}"

    async def acquire(
        self,
        *key_parts,
        ttl: Optional[int] = None,
        blocking: bool = True,
        blocking_timeout: Optional[float] = None,
        retry_interval: float = 0.2,
        jitter: float = 0.1,
        auto_renew: bool = False,
        auto_renew_interval: Optional[float] = None,
    ) -> bool:
        """
        Try to acquire the lock.

        Args:
            *key_parts: Parts for composing the lock key
            ttl: Lock TTL in seconds (defaults to self.default_ttl)
            blocking: If True, wait until lock is acquired or timeout
            blocking_timeout: Max seconds to wait when blocking=True.
                              None means wait forever; 0 means no wait (equivalent to blocking=False).
            retry_interval: Base sleep seconds between retries when blocking
            jitter: Add random(0, jitter) to each sleep to reduce thundering herd
            auto_renew: If True, start a background task to renew TTL
            auto_renew_interval: Seconds between renewals. Default is TTL*(1-margin)

        Returns:
            True if acquired, else False
        """
        self.lock_key = self._make_lock_key(*key_parts)
        self._ttl = int(ttl or self.default_ttl)
        self.fencing_token = None  # clear before acquiring

        # Non-blocking (or blocking_timeout=0): only try once
        if not blocking or (blocking_timeout is not None and blocking_timeout <= 0):
            acquired = await self.redis_client.set(
                self.lock_key, self.owner, nx=True, ex=self._ttl
            )
            self.acquired = bool(acquired)
        else:
            # Blocking mode: loop until acquired or timeout
            deadline = None if blocking_timeout is None else (time.monotonic() + blocking_timeout)
            while True:
                acquired = await self.redis_client.set(
                    self.lock_key, self.owner, nx=True, ex=self._ttl
                )
                if acquired:
                    self.acquired = True
                    break

                if deadline is not None and time.monotonic() >= deadline:
                    self.acquired = False
                    break

                sleep_for = retry_interval + random.uniform(0, max(jitter, 0))
                if deadline is not None:
                    remain = max(0.0, deadline - time.monotonic())
                    sleep_for = min(sleep_for, remain)
                    if sleep_for <= 0:
                        self.acquired = False
                        break
                await asyncio.sleep(sleep_for)

        if self.acquired:
            # Get fencing token (monotonic increasing count for the resource)
            try:
                token_key = self._make_fence_key()
                self.fencing_token = int(await self.redis_client.incr(token_key))
            except Exception as e:
                # If token generation fails, release lock and return failure (avoid writing without token)
                logger.error("Failed to generate fencing token: key={} owner={} err={}",
                             self.lock_key, self.owner, str(e))
                await self.release()
                return False

            logger.debug(
                "Acquired lock: key={} owner={} ttl={} token={}",
                self.lock_key, self.owner, self._ttl, self.fencing_token
            )

            if auto_renew:
                interval = auto_renew_interval or max(1.0, self._ttl * (1.0 - self._auto_renew_margin))
                self._auto_renew_interval = float(interval)
                self._start_auto_renew()
        else:
            logger.warning("Failed to acquire lock: key={} owner={}", self.lock_key, self.owner)

        return self.acquired

    async def extend(self, ttl: Optional[int] = None) -> bool:
        """
        Renew/refresh the TTL (set a fresh absolute TTL from now).

        Args:
            ttl: New TTL seconds from now (defaults to the last used TTL)

        Returns:
            True if renewed, False otherwise
        """
        if not self.lock_key or not self.acquired:
            return False

        new_ttl = int(ttl or self._ttl)
        try:
            res = await self._eval(_EXTEND_LUA, [self.lock_key], [self.owner, new_ttl])
            if res == 1:
                logger.debug("Extended lock: key={} owner={} ttl={}", self.lock_key, self.owner, new_ttl)
                self._ttl = new_ttl
                if self._auto_renew_task and not self._auto_renew_task.done():
                    self._auto_renew_interval = max(1.0, self._ttl * (1.0 - self._auto_renew_margin))
                return True
            else:
                logger.warning("Extend failed (not owner or missing): key={} owner={}", self.lock_key, self.owner)
                return False
        except Exception as e:
            logger.error("Error extending lock: key={} owner={} error={}", self.lock_key, self.owner, str(e))
            return False

    async def _eval(self, script: str, keys: list[str], args: list) -> int:
        return await self.redis_client.eval(script, len(keys), *keys, *args)            

    async def release(self) -> bool:
        """
        Release the lock if we own it (atomic check-and-del).
        """
        if not self.lock_key or not self.acquired:
            return False

        self._stop_auto_renew()

        try:
            res = await self._eval(_RELEASE_LUA, [self.lock_key], [self.owner])
            if res == 1:
                logger.debug("Released lock: key={} owner={}", self.lock_key, self.owner)
                self.acquired = False
                self.fencing_token = None  # avoid subsequent use of old token
                return True
            else:
                logger.warning("Cannot release lock - not owned: key={} owner={}", self.lock_key, self.owner)
                return False
        except Exception as e:
            logger.error("Error releasing lock: key={} owner={} error={}", self.lock_key, self.owner, str(e))
            return False

    def _start_auto_renew(self):
        if self._auto_renew_task and not self._auto_renew_task.done():
            return

        async def _loop():
            try:
                while self.acquired:
                    await asyncio.sleep(self._auto_renew_interval or max(1.0, self._ttl * (1.0 - self._auto_renew_margin)))
                    if not self.acquired:
                        break
                    ok = await self.extend(self._ttl)
                    if not ok:
                        logger.warning("Auto-renew failed; giving up: key={} owner={}", self.lock_key, self.owner)
                        self.acquired = False
                        self.fencing_token = None
                        break
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error("Auto-renew task crashed: key={} owner={} error={}", self.lock_key, self.owner, str(e))

        self._auto_renew_task = asyncio.create_task(_loop(), name=f"lock-autorenew:{self.lock_key}")

    def _stop_auto_renew(self):
        if self._auto_renew_task and not self._auto_renew_task.done():
            self._auto_renew_task.cancel()
        self._auto_renew_task = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.acquired:
            await self.release()

    def __bool__(self) -> bool:
        return self.acquired
