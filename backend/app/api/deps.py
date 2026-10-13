from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Request

from app.core.config import Policy, get_policy, get_settings


def policy_dep() -> Policy:
    return get_policy()


def correlation_id(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)


def tag(request: Request, **fields) -> None:
    """Attach ids to the request so the access log carries them (spec §14.1)."""
    for key, value in fields.items():
        if value is not None:
            setattr(request.state, key, str(value))


def aware(dt: datetime | None) -> datetime | None:
    """Naive query timestamps are interpreted in the replay timezone."""
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=ZoneInfo(get_settings().timezone))
