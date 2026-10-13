"""Idempotency records. scope = actor|session|operation; UNIQUE(scope, key) (spec §7.8)."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import IdempotencyRecord


def make_scope(actor_id: str, demo_session_id, operation: str) -> str:
    return f"{actor_id}|{demo_session_id}|{operation}"


def request_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def find(session: Session, scope: str, key: str) -> IdempotencyRecord | None:
    return session.scalar(select(IdempotencyRecord).where(IdempotencyRecord.scope == scope, IdempotencyRecord.key == key))


def find_for_actor(session: Session, actor_id: str, key: str) -> list[IdempotencyRecord]:
    return list(
        session.scalars(
            select(IdempotencyRecord)
            .where(IdempotencyRecord.actor_id == actor_id, IdempotencyRecord.key == key)
            .order_by(IdempotencyRecord.created_at)
        )
    )


def add(
    session: Session,
    *,
    scope: str,
    key: str,
    actor_id: str,
    operation: str,
    req_hash: str,
    http_status: int,
    response: dict,
    resource_type: str,
    resource_id: str,
) -> None:
    session.add(
        IdempotencyRecord(
            scope=scope,
            key=key,
            actor_id=actor_id,
            operation=operation,
            request_hash=req_hash,
            http_status=http_status,
            response=response,
            resource_type=resource_type,
            resource_id=resource_id,
        )
    )
