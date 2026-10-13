"""Append-only audit log: insert and select only (UPDATE/DELETE rejected by a DB trigger)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditEvent


def append(
    session: Session,
    *,
    actor_id: str,
    entity_type: str,
    entity_id: str,
    action: str,
    demo_session_id: uuid.UUID | None = None,
    previous_state: dict | None = None,
    new_state: dict | None = None,
    metadata: dict | None = None,
    correlation_id: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        demo_session_id=demo_session_id,
        actor_id=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        previous_state=previous_state,
        new_state=new_state,
        metadata_=metadata or {},
        correlation_id=correlation_id,
    )
    session.add(event)
    return event


def list_page(
    session: Session,
    *,
    demo_session_id: uuid.UUID | None,
    entity_type: str | None,
    entity_id: str | None,
    actor_id: str | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    after_seq: int | None,
    limit: int,
) -> list[AuditEvent]:
    q = select(AuditEvent)
    if demo_session_id:
        q = q.where(AuditEvent.demo_session_id == demo_session_id)
    if entity_type:
        q = q.where(AuditEvent.entity_type == entity_type)
    if entity_id:
        q = q.where(AuditEvent.entity_id == entity_id)
    if actor_id:
        q = q.where(AuditEvent.actor_id == actor_id)
    if from_ts:
        q = q.where(AuditEvent.created_at >= from_ts)
    if to_ts:
        q = q.where(AuditEvent.created_at <= to_ts)
    if after_seq is not None:
        q = q.where(AuditEvent.seq > after_seq)
    return list(session.scalars(q.order_by(AuditEvent.seq).limit(limit)))
