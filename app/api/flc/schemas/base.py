from typing import Generic, TypeVar

from app.cw.api.utils import ApiSuccess

T = TypeVar("T")


class CwOut(ApiSuccess, Generic[T]):
    """Standard API envelope used by public routers."""

    results: T  # type: ignore[valid-type]
