"""Pluggable caption engine interface."""

from __future__ import annotations

from typing import Protocol


class CaptionEngine(Protocol):
    def start(self) -> None: ...

    def handle_existing(self) -> None: ...

    async def aclose(self) -> None: ...
