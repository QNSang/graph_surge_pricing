"""Decisions and demo sessions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models import Decision, DemoSession
from app.domain.enums import FINAL_DECISION_STATUSES


def get_session(session: Session, demo_session_id: uuid.UUID) -> DemoSession | None:
    return session.get(DemoSession, demo_session_id)


def final_decision(session: Session, demo_session_id: uuid.UUID, proposal_id: str) -> Decision | None:
    return session.scalar(
        select(Decision).where(
            Decision.demo_session_id == demo_session_id,
            Decision.proposal_id == proposal_id,
            Decision.status.in_(FINAL_DECISION_STATUSES),
        )
    )


def finals_by_proposal(session: Session, demo_session_id: uuid.UUID, snapshot_id: str) -> dict[str, Decision]:
    rows = session.scalars(
        select(Decision).where(
            Decision.demo_session_id == demo_session_id,
            Decision.snapshot_id == snapshot_id,
            Decision.status.in_(FINAL_DECISION_STATUSES),
        )
    )
    return {d.proposal_id: d for d in rows}


def get(session: Session, decision_id: uuid.UUID) -> Decision | None:
    return session.get(Decision, decision_id)


def list_page(
    session: Session,
    *,
    actor_id: str | None,
    demo_session_id: uuid.UUID | None,
    snapshot_id: str | None,
    proposal_id: str | None,
    hex_id: str | None,
    action: str | None,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> list[Decision]:
    q = select(Decision)
    if actor_id:
        q = q.where(Decision.actor_id == actor_id)
    if demo_session_id:
        q = q.where(Decision.demo_session_id == demo_session_id)
    if snapshot_id:
        q = q.where(Decision.snapshot_id == snapshot_id)
    if proposal_id:
        q = q.where(Decision.proposal_id == proposal_id)
    if hex_id:
        q = q.where(Decision.hex_id == hex_id)
    if action:
        q = q.where(Decision.action == action)
    if after:
        ts, did = after
        q = q.where(or_(Decision.created_at > ts, and_(Decision.created_at == ts, Decision.decision_id > did)))
    return list(session.scalars(q.order_by(Decision.created_at, Decision.decision_id).limit(limit)))
