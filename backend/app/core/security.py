"""Demo authentication: server-issued static bearer tokens mapped to actor + role (spec §13)."""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.core.errors import AppError

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "OPERATOR": frozenset(
        {
            "snapshot.read",
            "recommendation.read",
            "decision.accept",
            "decision.override",
            "decision.keep",
            "batch.accept",
            "audit.read",
        }
    ),
    "VIEWER": frozenset({"snapshot.read", "recommendation.read", "audit.read"}),
}

ACTION_PERMISSION = {
    "ACCEPT_PROPOSAL": "decision.accept",
    "KEEP_BIDDING": "decision.keep",
    "OVERRIDE_PROPOSAL": "decision.override",
}


@dataclass(frozen=True)
class Actor:
    actor_id: str
    role: str

    def has(self, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS.get(self.role, frozenset())

    def require(self, permission: str) -> None:
        if not self.has(permission):
            raise AppError("PERMISSION_DENIED", f"Actor lacks permission '{permission}'.", {"permission": permission})


def parse_tokens(raw: str) -> dict[str, Actor]:
    tokens: dict[str, Actor] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        token, actor_id, role = entry.split(":")
        tokens[token] = Actor(actor_id=actor_id, role=role.upper())
    return tokens


_bearer = HTTPBearer(auto_error=False)


def get_actor(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Actor:
    if creds is None or creds.scheme.lower() != "bearer":
        raise AppError("UNAUTHENTICATED", "Missing bearer token.")
    for token, actor in parse_tokens(get_settings().demo_tokens).items():
        if hmac.compare_digest(token, creds.credentials):
            request.state.actor_id = actor.actor_id
            return actor
    raise AppError("UNAUTHENTICATED", "Invalid token.")


def require(permission: str):
    def _dep(actor: Actor = Depends(get_actor)) -> Actor:
        actor.require(permission)
        return actor

    return _dep
