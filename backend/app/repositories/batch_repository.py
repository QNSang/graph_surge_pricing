"""Batch plans (frozen previews), batches and per-item results."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BatchPlan, DecisionBatch, DecisionBatchItem


def get_plan(session: Session, plan_id: uuid.UUID) -> BatchPlan | None:
    return session.get(BatchPlan, plan_id)


def get_batch(session: Session, batch_id: uuid.UUID) -> DecisionBatch | None:
    return session.get(DecisionBatch, batch_id)


def batch_for_plan(session: Session, plan_id: uuid.UUID, *, for_update: bool = False) -> DecisionBatch | None:
    q = select(DecisionBatch).where(DecisionBatch.batch_plan_id == plan_id)
    if for_update:
        q = q.with_for_update()
    return session.scalar(q)


def items(session: Session, batch_id: uuid.UUID) -> list[DecisionBatchItem]:
    return list(
        session.scalars(
            select(DecisionBatchItem).where(DecisionBatchItem.batch_id == batch_id).order_by(DecisionBatchItem.position)
        )
    )


def get_item(session: Session, batch_id: uuid.UUID, proposal_id: str, *, for_update: bool = False) -> DecisionBatchItem | None:
    q = select(DecisionBatchItem).where(
        DecisionBatchItem.batch_id == batch_id, DecisionBatchItem.proposal_id == proposal_id
    )
    if for_update:
        q = q.with_for_update()
    return session.scalar(q)
