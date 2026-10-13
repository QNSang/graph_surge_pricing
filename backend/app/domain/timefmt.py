"""Timestamp formatting and opaque cursor helpers."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.errors import AppError


@lru_cache
def _tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def iso(dt: datetime | None) -> str | None:
    """ISO 8601 in the replay timezone (e.g. +07:00)."""
    return None if dt is None else dt.astimezone(_tz()).isoformat()


def encode_cursor(*parts) -> str:
    return base64.urlsafe_b64encode(json.dumps(parts, default=str).encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None, n: int) -> list | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        parts = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if not isinstance(parts, list) or len(parts) != n:
            raise ValueError
        return parts
    except ValueError as exc:
        raise AppError("INVALID_REQUEST", "Malformed cursor.", {"cursor": cursor}) from exc
