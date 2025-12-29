from __future__ import annotations

import asyncio

from loguru import logger

from app.shared.token_bucket import TokenBucket


async def acquire_with_backoff(
    token_bucket: TokenBucket,
    tokens: float = 1,
    *,
    max_attempts: int = 5,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
) -> bool:
    """
    Try to acquire tokens with exponential backoff to reduce thundering herds when the bucket is empty.
    """
    delay = base_delay

    for attempt in range(1, max_attempts + 1):
        if await token_bucket.acquire(tokens):
            if attempt > 1:
                logger.info(
                    "Acquired token after backoff (attempt {} of {})",
                    attempt,
                    max_attempts,
                )
            return True

        if attempt == max_attempts:
            logger.warning("Rate limit exceeded after {} attempts", max_attempts)
            return False

        logger.warning(
            "Rate limit exceeded, retrying in {} seconds (attempt {} of {})",
            delay,
            attempt,
            max_attempts,
        )
        await asyncio.sleep(delay)
        delay = min(delay * 2, max_delay)

    return False
