from slowapi import Limiter
from slowapi.util import get_remote_address

from app.app_config import get_app_environ_config

limiter = Limiter(key_func=get_remote_address)


def cw_rate_limit():
    return limiter.limit(get_app_environ_config().GLOBAL_API_RATE_LIMIT, key_func=lambda: "global")
