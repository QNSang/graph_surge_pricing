"""Single decisions (spec §6): one DB transaction writes decision + audit event + idempotency record.

Concurrency: the recommendation row is locked with SELECT ... FOR UPDATE, so concurrent requests on one proposal
serialise; the partial unique index uq_decision_final_per_session is the backstop (spec §6.6, BE-13).
DEMO only: there is no code path to a production pricing gateway (spec §13.3, BE-20).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Policy
from app.core.errors import AppError
from app.core.logging import metrics
from app.core.security import ACTION_PERMISSION, Actor
from app.db.models import Decision, DemoSession
from app.domain.enums import DecisionAction, DecisionStatus, Eligibility, RecommendationAction
from app.domain.policies import CAPABILITY_FOR_ACTION, ELIGIBILITY_ERROR, check_surge_value, fmt, parse_decimal
from app.domain.timefmt import decode_cursor, encode_cursor, iso
from app.repositories import audit_repository, decision_repository, idempotency_repository, recommendation_repository
from app.services import recommendation_service

log = logging.getLogger("surge.decision")

OPERATION = "decision.create"
EXECUTION_MODE = "DEMO"


@dataclass
class DecisionCommand:
    demo_session_id: uuid.UUID
    idempotency_key: str
    proposal_id: str
    expected_proposal_version: str
    snapshot_id: str
    action: str
    requested_surge: str | None = None
    reason: str | None = None
    recommendation_set_id: str | None = None
    expected_policy_version: str | None = None

    def fingerprint(self) -> dict:
        return {
            "demo_session_id": str(self.demo_session_id),
            "proposal_id": self.proposal_id,
            "expected_proposal_version": self.expected_proposal_version,
            "snapshot_id": self.snapshot_id,
            "action": self.action,
            "requested_surge": self.requested_surge,
            "reason": self.reason,
            "recommendation_set_id": self.recommendation_set_id,
            "expected_policy_version": self.expected_policy_version,
        }


def serialize(d: Decision) -> dict:
    return {
        "decision_id": str(d.decision_id),
        "demo_session_id": str(d.demo_session_id),
        "proposal_id": d.proposal_id,
        "proposal_version": d.proposal_version,
        "snapshot_id": d.snapshot_id,
        "recommendation_set_id": d.recommendation_set_id,
        "hex_id": d.hex_id,
        "action": d.action,
        "status": d.status,
        "surge_base": fmt(d.surge_base),
        "surge_proposed": fmt(d.surge_proposed),
        "requested_surge": fmt(d.requested_surge),
        "surge_decided": fmt(d.surge_decided),
        "reason": d.reason,
        "actor_id": d.actor_id,
        "batch_id": str(d.batch_id) if d.batch_id else None,
        "provider": {"id": d.provider_id, "version": d.provider_version},
        "policy_version": d.policy_version,
        "execution_mode": d.execution_mode,
        "production_effective": False,
        "created_at": iso(d.created_at),
        "recorded_at": iso(d.recorded_at),
    }


def require_owned_session(session: Session, actor: Actor, demo_session_id: uuid.UUID) -> DemoSession:
    demo = decision_repository.get_session(session, demo_session_id)
    if demo is None:
        raise AppError("SESSION_NOT_FOUND", "Demo session not found.", {"demo_session_id": str(demo_session_id)})
    if demo.actor_id != actor.actor_id:
        raise AppError("PERMISSION_DENIED", "Demo session belongs to another actor.", {"demo_session_id": str(demo_session_id)})
    if demo.status != "ACTIVE":
        raise AppError("INVALID_REQUEST", "Demo session is closed.", {"demo_session_id": str(demo_session_id)})
    return demo


def _decided_surge(cmd: DecisionCommand, rec, policy: Policy, ctx: dict) -> tuple[Decimal | None, Decimal, str]:
    """Return (requested_surge, surge_decided, status). Client surge is ignored for ACCEPT (spec §9.1)."""
    if cmd.action == DecisionAction.ACCEPT_PROPOSAL:
        check_surge_value(rec.surge_proposed, rec.surge_base, policy.limits, ctx)
        return None, rec.surge_proposed, DecisionStatus.RECORDED.value
    if cmd.action == DecisionAction.KEEP_BIDDING:
        return None, rec.surge_base, DecisionStatus.KEPT_BIDDING.value
    # OVERRIDE_PROPOSAL
    if cmd.requested_surge is None:
        raise AppError("INVALID_REQUEST", "requested_surge is required for OVERRIDE_PROPOSAL.", ctx)
    if policy.override_requires_reason and not (cmd.reason and cmd.reason.strip()):
        raise AppError("REASON_REQUIRED", "A reason is required for a manual override.", ctx)
    try:
        requested = parse_decimal(cmd.requested_surge)
    except ValueError as exc:
        raise AppError("INVALID_REQUEST", "requested_surge must be a finite decimal string.", ctx) from exc
    check_surge_value(requested, rec.surge_base, policy.limits, {**ctx, "requested_surge": cmd.requested_surge})
    return requested, requested, DecisionStatus.RECORDED.value


def record(
    session: Session,
    actor: Actor,
    cmd: DecisionCommand,
    policy: Policy,
    *,
    correlation_id: str | None,
    batch_id: uuid.UUID | None = None,
    store_idempotency: bool = True,
    before_commit: Callable[[Decision], None] | None = None,
) -> tuple[int, dict, bool]:
    """Validate and persist one decision. Returns (http_status, body, replayed). Rolls back on any error."""
    try:
        return _record(session, actor, cmd, policy, correlation_id, batch_id, store_idempotency, before_commit)
    except AppError as err:
        session.rollback()
        metrics.inc("decision_failure_count")
        log.info("decision rejected", extra={"fields": {"code": err.code, "proposal_id": cmd.proposal_id}})
        raise
    except Exception:
        session.rollback()
        metrics.inc("decision_failure_count")
        raise


def _record(session, actor, cmd, policy, correlation_id, batch_id, store_idempotency, before_commit):
    if cmd.action not in ACTION_PERMISSION:
        raise AppError("INVALID_REQUEST", "Unknown decision action.", {"action": cmd.action})
    actor.require(ACTION_PERMISSION[cmd.action])
    require_owned_session(session, actor, cmd.demo_session_id)

    scope = idempotency_repository.make_scope(actor.actor_id, cmd.demo_session_id, OPERATION)
    req_hash = idempotency_repository.request_hash(cmd.fingerprint())
    if store_idempotency:
        replay = _replay(session, scope, cmd.idempotency_key, req_hash)
        if replay is not None:
            return replay

    ctx = {"proposal_id": cmd.proposal_id, "snapshot_id": cmd.snapshot_id}
    rec = recommendation_repository.get(session, cmd.proposal_id, for_update=True)
    if rec is None:
        raise AppError("PROPOSAL_NOT_FOUND", "Proposal not found.", ctx)
    if store_idempotency:
        # A same-key request may have committed while we waited for the row lock.
        replay = _replay(session, scope, cmd.idempotency_key, req_hash)
        if replay is not None:
            session.rollback()
            return replay
    if rec.snapshot_id != cmd.snapshot_id:
        raise AppError("SNAPSHOT_MISMATCH", "Proposal does not belong to this snapshot.", ctx)
    if cmd.recommendation_set_id and rec.recommendation_set_id != cmd.recommendation_set_id:
        raise AppError("RECOMMENDATION_SET_MISMATCH", "Proposal does not belong to this recommendation set.", ctx)
    if rec.proposal_version != cmd.expected_proposal_version:
        raise AppError(
            "PROPOSAL_VERSION_CONFLICT",
            "Proposal version changed.",
            {**ctx, "expected": cmd.expected_proposal_version, "actual": rec.proposal_version},
        )
    if cmd.expected_policy_version and cmd.expected_policy_version != policy.policy_version:
        raise AppError(
            "POLICY_VERSION_CONFLICT",
            "Policy changed since the proposal was loaded.",
            {**ctx, "expected": cmd.expected_policy_version, "current": policy.policy_version},
        )

    current = recommendation_repository.latest_published_set(session, rec.snapshot_id)
    elig = recommendation_service.evaluate(rec, current.recommendation_set_id if current else None, policy)
    if elig.state != Eligibility.ELIGIBLE:
        code = elig.blocked_reasons[0] if elig.blocked_reasons and elig.blocked_reasons[0] in (
            "POLICY_VERSION_CONFLICT",
            "SURGE_LIMIT_EXCEEDED",
            "INVALID_SURGE_STEP",
            "INVALID_SURGE_PRECISION",
        ) else ELIGIBILITY_ERROR[elig.state]
        raise AppError(code, f"Proposal is {elig.state.value}.", {**ctx, "eligibility": elig.state.value, "reasons": elig.blocked_reasons})
    if rec.action == RecommendationAction.REVIEW:
        raise AppError("REVIEW_REQUIRED", "REVIEW proposals cannot be decided in the MVP.", ctx)
    if not elig.capabilities.get(CAPABILITY_FOR_ACTION[DecisionAction(cmd.action)]):
        raise AppError("ACTION_NOT_ALLOWED", f"{cmd.action} is not allowed for a {rec.action} proposal.", ctx)
    existing = decision_repository.final_decision(session, cmd.demo_session_id, rec.proposal_id)
    if existing is not None:
        raise AppError(
            "DECISION_ALREADY_EXISTS",
            "Proposal already has a final decision in this demo session.",
            {**ctx, "decision_id": str(existing.decision_id), "status": existing.status},
        )

    requested, decided, status = _decided_surge(cmd, rec, policy, ctx)
    rset = recommendation_repository.get_set(session, rec.recommendation_set_id)
    decision = Decision(
        decision_id=uuid.uuid4(),
        demo_session_id=cmd.demo_session_id,
        proposal_id=rec.proposal_id,
        proposal_version=rec.proposal_version,
        snapshot_id=rec.snapshot_id,
        recommendation_set_id=rec.recommendation_set_id,
        hex_id=rec.hex_id,
        action=cmd.action,
        surge_base=rec.surge_base,
        surge_proposed=rec.surge_proposed,
        requested_surge=requested,
        surge_decided=decided,
        reason=cmd.reason,
        status=status,
        actor_id=actor.actor_id,
        idempotency_key=cmd.idempotency_key,
        batch_id=batch_id,
        policy_version=policy.policy_version,
        provider_id=rset.provider_id,
        provider_version=rset.provider_version,
        execution_mode=EXECUTION_MODE,
        recorded_at=datetime.now(UTC),
    )
    session.add(decision)
    try:
        session.flush()
    except IntegrityError as exc:
        raise AppError("DECISION_ALREADY_EXISTS", "Proposal already has a final decision in this demo session.", ctx) from exc
    session.refresh(decision)
    body = serialize(decision)

    audit_repository.append(
        session,
        actor_id=actor.actor_id,
        entity_type="decision",
        entity_id=str(decision.decision_id),
        action=f"DECISION_{cmd.action}",
        demo_session_id=cmd.demo_session_id,
        previous_state=None,
        new_state=body,
        metadata={
            "proposal_id": rec.proposal_id,
            "snapshot_id": rec.snapshot_id,
            "recommendation_action": rec.action,
            "provider": {"id": rset.provider_id, "version": rset.provider_version},
            "validation_status": rec.validation_status,
            "eligibility": elig.state.value,
            "idempotency_key": cmd.idempotency_key,
            "batch_id": str(batch_id) if batch_id else None,
        },
        correlation_id=correlation_id,
    )
    if store_idempotency:
        idempotency_repository.add(
            session,
            scope=scope,
            key=cmd.idempotency_key,
            actor_id=actor.actor_id,
            operation=OPERATION,
            req_hash=req_hash,
            http_status=201,
            response=body,
            resource_type="decision",
            resource_id=str(decision.decision_id),
        )
    if before_commit is not None:
        before_commit(decision)
    try:
        session.flush()
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        # Lost an idempotency race: the other request committed first with the same key.
        if store_idempotency:
            replay = _replay(session, scope, cmd.idempotency_key, req_hash)
            if replay is not None:
                return replay
        raise AppError("DECISION_ALREADY_EXISTS", "Concurrent decision recorded first.", ctx) from exc
    metrics.inc("decision_success_count")
    return 201, body, False


def _replay(session: Session, scope: str, key: str, req_hash: str) -> tuple[int, dict, bool] | None:
    record_ = idempotency_repository.find(session, scope, key)
    if record_ is None:
        return None
    if record_.request_hash != req_hash:
        raise AppError("IDEMPOTENCY_CONFLICT", "Idempotency key reused with a different payload.", {"idempotency_key": key})
    metrics.inc("idempotency_replay_count")
    return record_.http_status, record_.response, True


def by_idempotency(session: Session, actor: Actor, key: str) -> dict:
    records = idempotency_repository.find_for_actor(session, actor.actor_id, key)
    if not records:
        raise AppError("NOT_FOUND", "No operation recorded for this idempotency key.", {"idempotency_key": key})
    r = records[-1]
    return {
        "idempotency_key": key,
        "operation": r.operation,
        "resource_type": r.resource_type,
        "resource_id": r.resource_id,
        "http_status": r.http_status,
        "response": r.response,
        "created_at": iso(r.created_at),
    }


def get(session: Session, actor: Actor, decision_id: uuid.UUID) -> dict:
    d = decision_repository.get(session, decision_id)
    if d is None:
        raise AppError("NOT_FOUND", "Decision not found.", {"decision_id": str(decision_id)})
    return serialize(d)


def list_decisions(
    session: Session,
    *,
    actor_id: str | None,
    demo_session_id: uuid.UUID | None,
    snapshot_id: str | None,
    proposal_id: str | None,
    hex_id: str | None,
    action: str | None,
    cursor: str | None,
    limit: int,
) -> dict:
    after = decode_cursor(cursor, 2)
    after_key = (datetime.fromisoformat(after[0]), uuid.UUID(after[1])) if after else None
    rows = decision_repository.list_page(
        session,
        actor_id=actor_id,
        demo_session_id=demo_session_id,
        snapshot_id=snapshot_id,
        proposal_id=proposal_id,
        hex_id=hex_id,
        action=action,
        after=after_key,
        limit=limit + 1,
    )
    page = rows[:limit]
    nxt = encode_cursor(page[-1].created_at.isoformat(), str(page[-1].decision_id)) if len(rows) > limit else None
    return {"items": [serialize(d) for d in page], "next_cursor": nxt}


# --- demo sessions --------------------------------------------------------------------------------------------


def serialize_session(s: DemoSession) -> dict:
    return {
        "demo_session_id": str(s.demo_session_id),
        "actor_id": s.actor_id,
        "name": s.name,
        "status": s.status,
        "execution_mode": EXECUTION_MODE,
        "metadata": s.metadata_,
        "created_at": iso(s.created_at),
    }


def create_session(session: Session, actor: Actor, name: str | None, correlation_id: str | None) -> dict:
    demo = DemoSession(demo_session_id=uuid.uuid4(), actor_id=actor.actor_id, name=name or f"demo-{actor.actor_id}")
    session.add(demo)
    session.flush()
    audit_repository.append(
        session,
        actor_id=actor.actor_id,
        entity_type="demo_session",
        entity_id=str(demo.demo_session_id),
        action="DEMO_SESSION_CREATED",
        demo_session_id=demo.demo_session_id,
        new_state={"name": demo.name},
        correlation_id=correlation_id,
    )
    session.commit()
    session.refresh(demo)
    return serialize_session(demo)


def get_session(session: Session, actor: Actor, demo_session_id: uuid.UUID) -> dict:
    demo = decision_repository.get_session(session, demo_session_id)
    if demo is None:
        raise AppError("SESSION_NOT_FOUND", "Demo session not found.", {"demo_session_id": str(demo_session_id)})
    if demo.actor_id != actor.actor_id and actor.role != "VIEWER":
        raise AppError("PERMISSION_DENIED", "Demo session belongs to another actor.")
    return serialize_session(demo)
