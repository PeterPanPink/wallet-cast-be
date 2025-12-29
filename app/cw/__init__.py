"""
CW Library (Sanitized Demo)
"""
import asyncio


def _ensure_default_event_loop() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            # Python 3.14+ requires creating the default loop explicitly.
            asyncio.set_event_loop(asyncio.new_event_loop())


_ensure_default_event_loop()