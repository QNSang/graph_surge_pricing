"""Batch preview/commit (spec §7). Preview freezes a plan; commit processes each item in its own transaction.

Crash safety: the batch and its PENDING items are committed before any item is processed, and each item's
decision + audit + item status commit together. Re-committing the same plan resumes the existing batch
(UNIQUE batch_plan_id) and only processes items still PENDING, so no duplicate decisions are created (BE-21).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Policy
from app.core.errors import AppError
from app.core.logging import metrics
from app.core.security import Actor
from app.db.models import BatchPlan, DecisionBatch, DecisionBatchItem
from app.domain.enums import (
    BatchItemStatus,
    BatchStatus,
    DecisionAction,
    Eligibility,
    RecommendationAction,
    SelectionMode,
)
from app.domain.policies import ELIGIBILITY_ERROR, fmt
from app.domain.timefmt import iso
from app.repositories import (
    audit_repository,
    batch_repository,
    decision_repository,
    idempotency_repository,
    recommendation_repository,
    snapshot_repository,
)
from app.services import decision_service, recommendation_service

OPERATION = "batch.commit"
_MOVABLE = (RecommendationAction.INCREASE, RecommendationAction.DECREASE)


def _skip_reason(view: recommendation_service.ProposalView) -> str | None:
    if view.decision is not None:
        return "DECISION_ALREADY_EXISTS"
    state = view.eligibility.state
    if state != Eligibility.ELIGIBLE:
        reasons = view.eligibility.blocked_reasons
        return reasons[0] if reasons else ELIGIBILITY_ERROR[state]
    if view.rec.action == RecommendationAction.REVIEW:
        return "REVIEW_REQUIRED"
    if view.rec.action == RecommendationAction.HOLD:
        return "HOLD_NO_ACTION"
    return None


def preview(
    session: Session,
    actor: Actor,
    policy: Policy,
    *,
    demo_session_id: uuid.UUID,
    snapshot_id: str,
    recommendation_set_id: str,
    selection_mode: str,
    proposal_ids: list[str] | None,
    correlation_id: str | None,
) -> dict:
    actor.require("batch.accept")
    decision_service.require_owned_session(session, actor, demo_session_id)
    if snapshot_repository.get(session, snapshot_id) is None:
        raise AppError("SNAPSHOT_NOT_FOUND", "Snapshot not found.", {"snapshot_id": snapshot_id})
    rset, current_id = recommendation_service.resolve_set(session, snapshot_id, recommendation_set_id)

    if selection_mode == SelectionMode.SELECTED:
        if not proposal_ids:
            raise AppError("INVALID_REQUEST", "proposal_ids is required for SELECTED.")
        if len(set(proposal_ids)) != len(proposal_ids):
            raise AppError("INVALID_REQUEST", "proposal_ids contains duplicates.")
        recs = recommendation_repository.get_many(session, proposal_ids)
        found = {r.proposal_id for r in recs}
        missing = [p for p in proposal_ids if p not in found]
        if missing:
            raise AppError("PROPOSAL_NOT_FOUND", "Some proposals do not exist.", {"proposal_ids": missing})
        # A batch may not mix snapshots or recommendation sets (spec §7.2, BE-09).
        foreign_snap = [r.proposal_id for r in recs if r.snapshot_id != snapshot_id]
        if foreign_snap:
            raise AppError("SNAPSHOT_MISMATCH", "Batch mixes snapshots.", {"proposal_ids": foreign_snap})
        foreign_set = [r.proposal_id for r in recs if r.recommendation_set_id != rset.recommendation_set_id]
        if foreign_set:
            raise AppError("RECOMMENDATION_SET_MISMATCH", "Batch mixes recommendation sets.", {"proposal_ids": foreign_set})
        order = {p: i for i, p in enumerate(proposal_ids)}
        recs.sort(key=lambda r: order[r.proposal_id])
    elif selection_mode == SelectionMode.ALL_ELIGIBLE:
        if proposal_ids:
            raise AppError("INVALID_REQUEST", "proposal_ids must be empty for ALL_ELIGIBLE.")
        recs = recommendation_repository.for_set(session, rset.recommendation_set_id)
    else:
        raise AppError("INVALID_REQUEST", "Unknown selection_mode.", {"selection_mode": selection_mode})

    finals = decision_repository.finals_by_proposal(session, demo_session_id, snapshot_id)
    items, skipped, response_items = [], [], []
    for rec in recs:
        view = recommendation_service.ProposalView(
            rec, rset, recommendation_service.evaluate(rec, current_id, policy), finals.get(rec.proposal_id)
        )
        reason = _skip_reason(view)
        base = {
            "proposal_id": rec.proposal_id,
            "proposal_version": rec.proposal_version,
            "hex_id": rec.hex_id,
            "action": rec.action,
            "surge_base": fmt(rec.surge_base),
            "surge_proposed": fmt(rec.surge_proposed),
        }
        if reason is None and rec.action in _MOVABLE:
            items.append(base)
            response_items.append({**base, "eligible": True})
        else:
            skipped.append({**base, "reason_code": reason})
            response_items.append({**base, "eligible": False, "reason_code": reason})

    now = datetime.now(UTC)
    plan = BatchPlan(
        batch_plan_id=uuid.uuid4(),
        demo_session_id=demo_session_id,
        actor_id=actor.actor_id,
        snapshot_id=snapshot_id,
        recommendation_set_id=rset.recommendation_set_id,
        selection_mode=selection_mode,
        items=items,
        skipped=skipped,
        expires_at=now + timedelta(minutes=policy.batch_plan_ttl_minutes),
    )
    session.add(plan)
    audit_repository.append(
        session,
        actor_id=actor.actor_id,
        entity_type="batch_plan",
        entity_id=str(plan.batch_plan_id),
        action="BATCH_PREVIEWED",
        demo_session_id=demo_session_id,
        new_state={"eligible_count": len(items), "skipped_count": len(skipped), "selection_mode": selection_mode},
        metadata={"snapshot_id": snapshot_id, "recommendation_set_id": rset.recommendation_set_id},
        correlation_id=correlation_id,
    )
    session.commit()
    return {
        "batch_plan_id": str(plan.batch_plan_id),
        "demo_session_id": str(demo_session_id),
        "snapshot_id": snapshot_id,
        "recommendation_set_id": rset.recommendation_set_id,
        "selection_mode": selection_mode,
        "total_candidates": len(recs),
        "eligible_count": len(items),
        "skipped_count": len(skipped),
        "items": response_items,
        "expires_at": iso(plan.expires_at),
    }


def _serialize_batch(batch: DecisionBatch, items: list[DecisionBatchItem]) -> dict:
    return {
        "batch_id": str(batch.batch_id),
        "batch_plan_id": str(batch.batch_plan_id),
        "demo_session_id": str(batch.demo_session_id),
        "snapshot_id": batch.snapshot_id,
        "recommendation_set_id": batch.recommendation_set_id,
        "status": batch.status,
        "total": batch.total_count,
        "succeeded": batch.success_count,
        "failed": batch.failure_count,
        "execution_mode": decision_service.EXECUTION_MODE,
        "production_effective": False,
        "created_at": iso(batch.created_at),
        "completed_at": iso(batch.completed_at),
        "results": [
            {
                "proposal_id": i.proposal_id,
                "proposal_version": i.proposal_version,
                "status": i.status,
                "decision_id": str(i.decision_id) if i.decision_id else None,
                "error_code": i.error_code,
                "error_message": i.error_message,
            }
            for i in items
        ],
    }


def _start_batch(session: Session, actor: Actor, plan: BatchPlan, key: str, correlation_id: str | None) -> DecisionBatch:
    existing = batch_repository.batch_for_plan(session, plan.batch_plan_id)
    if existing is not None:
        return existing
    if plan.expires_at <= datetime.now(UTC):
        raise AppError(
            "BATCH_PLAN_EXPIRED",
            "Batch plan expired; preview again.",
            {"batch_plan_id": str(plan.batch_plan_id), "expires_at": iso(plan.expires_at)},
        )
    batch = DecisionBatch(
        batch_id=uuid.uuid4(),
        batch_plan_id=plan.batch_plan_id,
        demo_session_id=plan.demo_session_id,
        snapshot_id=plan.snapshot_id,
        recommendation_set_id=plan.recommendation_set_id,
        actor_id=actor.actor_id,
        idempotency_key=key,
        status=BatchStatus.PROCESSING.value,
        total_count=len(plan.items),
    )
    session.add(batch)
    session.flush()
    session.add_all(
        DecisionBatchItem(
            batch_id=batch.batch_id,
            proposal_id=item["proposal_id"],
            proposal_version=item["proposal_version"],
            position=pos,
            requested_action=DecisionAction.ACCEPT_PROPOSAL.value,
            status=BatchItemStatus.PENDING.value,
        )
        for pos, item in enumerate(plan.items)
    )
    audit_repository.append(
        session,
        actor_id=actor.actor_id,
        entity_type="batch",
        entity_id=str(batch.batch_id),
        action="BATCH_STARTED",
        demo_session_id=plan.demo_session_id,
        new_state={"total": batch.total_count},
        metadata={"batch_plan_id": str(plan.batch_plan_id), "idempotency_key": key},
        correlation_id=correlation_id,
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()  # concurrent commit of the same plan won; resume it
        return batch_repository.batch_for_plan(session, plan.batch_plan_id)
    return batch


def _process_item(session, actor, policy, batch, item, correlation_id) -> None:
    cmd = decision_service.DecisionCommand(
        demo_session_id=batch.demo_session_id,
        idempotency_key=f"batch:{batch.batch_id}:{item.proposal_id}",
        proposal_id=item.proposal_id,
        expected_proposal_version=item.proposal_version,
        snapshot_id=batch.snapshot_id,
        action=item.requested_action,
        recommendation_set_id=batch.recommendation_set_id,
    )
    batch_id, proposal_id = batch.batch_id, item.proposal_id

    def mark_success(decision) -> None:
        locked = batch_repository.get_item(session, batch_id, proposal_id, for_update=True)
        locked.status = BatchItemStatus.SUCCESS.value
        locked.decision_id = decision.decision_id
        locked.updated_at = datetime.now(UTC)

    try:
        decision_service.record(
            session,
            actor,
            cmd,
            policy,
            correlation_id=correlation_id,
            batch_id=batch_id,
            store_idempotency=False,
            before_commit=mark_success,
        )
    except AppError as err:
        failed = batch_repository.get_item(session, batch_id, proposal_id, for_update=True)
        if failed.status == BatchItemStatus.PENDING:
            failed.status = BatchItemStatus.FAILED.value
            failed.error_code = err.code
            failed.error_message = err.message
            failed.updated_at = datetime.now(UTC)
        session.commit()


def _finalise(session: Session, actor: Actor, batch: DecisionBatch, correlation_id: str | None) -> DecisionBatch:
    batch = batch_repository.batch_for_plan(session, batch.batch_plan_id, for_update=True)
    if batch.status != BatchStatus.PROCESSING:
        session.rollback()
        return batch
    items = batch_repository.items(session, batch.batch_id)
    if any(i.status == BatchItemStatus.PENDING for i in items):
        session.rollback()
        return batch
    ok = sum(1 for i in items if i.status == BatchItemStatus.SUCCESS)
    bad = len(items) - ok
    if bad == 0:
        status = BatchStatus.SUCCESS
    elif ok == 0:
        status = BatchStatus.FAILED
    else:
        status = BatchStatus.PARTIAL_SUCCESS
        metrics.inc("batch_partial_success_count")
    batch.status = status.value
    batch.success_count = ok
    batch.failure_count = bad
    batch.completed_at = datetime.now(UTC)
    audit_repository.append(
        session,
        actor_id=actor.actor_id,
        entity_type="batch",
        entity_id=str(batch.batch_id),
        action="BATCH_COMPLETED",
        demo_session_id=batch.demo_session_id,
        previous_state={"status": BatchStatus.PROCESSING.value},
        new_state={"status": status.value, "succeeded": ok, "failed": bad},
        correlation_id=correlation_id,
    )
    session.commit()
    return batch


def commit(
    session: Session,
    actor: Actor,
    policy: Policy,
    *,
    demo_session_id: uuid.UUID,
    batch_plan_id: uuid.UUID,
    idempotency_key: str,
    correlation_id: str | None,
) -> tuple[int, dict, bool]:
    actor.require("batch.accept")
    decision_service.require_owned_session(session, actor, demo_session_id)
    scope = idempotency_repository.make_scope(actor.actor_id, demo_session_id, OPERATION)
    req_hash = idempotency_repository.request_hash({"demo_session_id": str(demo_session_id), "batch_plan_id": str(batch_plan_id)})
    record_ = idempotency_repository.find(session, scope, idempotency_key)
    if record_ is not None:
        if record_.request_hash != req_hash:
            raise AppError("IDEMPOTENCY_CONFLICT", "Idempotency key reused with a different payload.", {"idempotency_key": idempotency_key})
        metrics.inc("idempotency_replay_count")
        return record_.http_status, record_.response, True

    plan = batch_repository.get_plan(session, batch_plan_id)
    if plan is None:
        raise AppError("NOT_FOUND", "Batch plan not found.", {"batch_plan_id": str(batch_plan_id)})
    if plan.demo_session_id != demo_session_id or plan.actor_id != actor.actor_id:
        raise AppError("PERMISSION_DENIED", "Batch plan belongs to another session or actor.", {"batch_plan_id": str(batch_plan_id)})

    batch = _start_batch(session, actor, plan, idempotency_key, correlation_id)
    for item in batch_repository.items(session, batch.batch_id):
        if item.status == BatchItemStatus.PENDING:
            _process_item(session, actor, policy, batch, item, correlation_id)
    batch = _finalise(session, actor, batch, correlation_id)
    body = _serialize_batch(batch, batch_repository.items(session, batch.batch_id))

    if batch.status != BatchStatus.PROCESSING:
        try:
            idempotency_repository.add(
                session,
                scope=scope,
                key=idempotency_key,
                actor_id=actor.actor_id,
                operation=OPERATION,
                req_hash=req_hash,
                http_status=200,
                response=body,
                resource_type="batch",
                resource_id=str(batch.batch_id),
            )
            session.commit()
        except IntegrityError:
            session.rollback()
    return 200, body, False


def get(session: Session, actor: Actor, batch_id: uuid.UUID) -> dict:
    batch = batch_repository.get_batch(session, batch_id)
    if batch is None:
        raise AppError("NOT_FOUND", "Batch not found.", {"batch_id": str(batch_id)})
    if batch.actor_id != actor.actor_id and actor.role != "VIEWER":
        raise AppError("PERMISSION_DENIED", "Batch belongs to another actor.")
    return _serialize_batch(batch, batch_repository.items(session, batch.batch_id))
