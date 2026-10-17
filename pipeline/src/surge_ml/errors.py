"""Fail-closed technical errors, separate from recommendation actions."""
from __future__ import annotations


class GGSOError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise GGSOError(code, message)
