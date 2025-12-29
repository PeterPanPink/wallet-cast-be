from typing import Generic, TypeVar

from app.shared.api.utils import ApiSuccess

T = TypeVar("T")


class ApiOut(ApiSuccess, Generic[T]):
    """Standard API envelope used by public routers."""

    results: T  # type: ignore[valid-type]
