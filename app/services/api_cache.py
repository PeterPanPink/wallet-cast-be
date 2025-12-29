from fastapi_cache.decorator import cache


def cw_cache(expire_seconds: int | None = 60):
    """
    Wrapper around fastapi_cache.decorator.cache with default expire_seconds.

    Args:
        expire_seconds: Cache expiration time in seconds (default: 60)

    Returns:
        cache decorator configured with the specified expiration time
    """
    return cache(expire=expire_seconds)
