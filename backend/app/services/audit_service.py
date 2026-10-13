"""Audit event queries. Writes happen inside the business transaction via audit_repository.append."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import AuditEvent
from app.domain.timefmt import decode_cursor, encode_cursor, iso
from app.repositories import audit_repository


def serialize(e: AuditEvent) -> dict:
    return {
        "event_id": str(e.event_id),
        "seq": e.seq,
        "demo_session_id": str(e.demo_session_id) if e.demo_session_id else None,
        "actor_id": e.actor_id,
        "entity_type": e.entity_type,
        "entity_id": e.entity_id,
        "action": e.action,
        "previous_state": e.previous_state,
        "new_state": e.new_state,
        "metadata": e.metadata_,
        "correlation_id": e.correlation_id,
        "created_at": iso(e.created_at),
    }


def list_events(
    session: Session,
    *,
    demo_session_id: uuid.UUID | None,
    entity_type: str | None,
    entity_id: str | None,
    actor_id: str | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    cursor: str | None,
    limit: int,
) -> dict:
    after = decode_cursor(cursor, 1)
    rows = audit_repository.list_page(
        session,
        demo_session_id=demo_session_id,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        from_ts=from_ts,
        to_ts=to_ts,
        after_seq=int(after[0]) if after else None,
        limit=limit + 1,
    )
    page = rows[:limit]
    return {
        "items": [serialize(e) for e in page],
        "next_cursor": encode_cursor(page[-1].seq) if len(rows) > limit else None,
    }
