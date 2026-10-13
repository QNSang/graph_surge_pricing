"""Decision, batch, demo-session and audit APIs (spec §8.4–8.6, §9)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import aware, correlation_id, policy_dep, tag
from app.core.config import Policy
from app.core.security import Actor, get_actor, require
from app.db.session import get_db
from app.schemas.requests import BatchCommitRequest, BatchPreviewRequest, DecisionRequest, DemoSessionCreate
from app.schemas.responses import (
    ERROR_RESPONSES,
    BatchPreviewResponse,
    BatchResultResponse,
    DecisionResponse,
    DemoSessionResponse,
)
from app.services import audit_service, batch_service, decision_service

router = APIRouter(responses=ERROR_RESPONSES)


@router.post(
    "/decisions",
    tags=["decisions"],
    status_code=201,
    response_model=DecisionResponse,
    summary="Record one DEMO decision (accept / keep base / override)",
)
def create_decision(
    body: DecisionRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    policy: Policy = Depends(policy_dep),
    actor: Actor = Depends(get_actor),
) -> dict[str, Any]:
    tag(request, demo_session_id=body.demo_session_id, snapshot_id=body.snapshot_id, proposal_id=body.proposal_id)
    cmd = decision_service.DecisionCommand(**body.model_dump(exclude={"schema_version"}))
    status, payload, replayed = decision_service.record(db, actor, cmd, policy, correlation_id=correlation_id(request))
    response.status_code = status
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return payload


@router.get("/decisions", tags=["decisions"], summary="Decision history")
def list_decisions(
    demo_session_id: uuid.UUID | None = None,
    snapshot_id: str | None = None,
    proposal_id: str | None = None,
    hex_id: str | None = None,
    action: str | None = None,
    actor_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: Actor = Depends(require("audit.read")),
) -> dict[str, Any]:
    return decision_service.list_decisions(
        db,
        actor_id=actor_id,
        demo_session_id=demo_session_id,
        snapshot_id=snapshot_id,
        proposal_id=proposal_id,
        hex_id=hex_id,
        action=action,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/decisions/by-idempotency/{key}",
    tags=["decisions"],
    summary="Look up the outcome of a mutation by idempotency key (after a timeout)",
)
def decision_by_idempotency(key: str, db: Session = Depends(get_db), actor: Actor = Depends(get_actor)) -> dict[str, Any]:
    return decision_service.by_idempotency(db, actor, key)


@router.get("/decisions/{decision_id}", tags=["decisions"], response_model=DecisionResponse, summary="Decision detail")
def decision_detail(
    decision_id: uuid.UUID, db: Session = Depends(get_db), actor: Actor = Depends(require("audit.read"))
) -> dict[str, Any]:
    return decision_service.get(db, actor, decision_id)


@router.post(
    "/batches/preview",
    tags=["batches"],
    status_code=201,
    response_model=BatchPreviewResponse,
    summary="Freeze a batch plan (Accept All / Accept Selected)",
)
def batch_preview(
    body: BatchPreviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    policy: Policy = Depends(policy_dep),
    actor: Actor = Depends(get_actor),
) -> dict[str, Any]:
    tag(request, demo_session_id=body.demo_session_id, snapshot_id=body.snapshot_id)
    return batch_service.preview(
        db,
        actor,
        policy,
        demo_session_id=body.demo_session_id,
        snapshot_id=body.snapshot_id,
        recommendation_set_id=body.recommendation_set_id,
        selection_mode=body.selection_mode,
        proposal_ids=body.proposal_ids,
        correlation_id=correlation_id(request),
    )


@router.post(
    "/decisions/batch",
    tags=["batches"],
    response_model=BatchResultResponse,
    summary="Commit a frozen batch plan (partial success, resumable)",
)
def batch_commit(
    body: BatchCommitRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    policy: Policy = Depends(policy_dep),
    actor: Actor = Depends(get_actor),
) -> dict[str, Any]:
    tag(request, demo_session_id=body.demo_session_id)
    status, payload, replayed = batch_service.commit(
        db,
        actor,
        policy,
        demo_session_id=body.demo_session_id,
        batch_plan_id=body.batch_plan_id,
        idempotency_key=body.idempotency_key,
        correlation_id=correlation_id(request),
    )
    tag(request, batch_id=payload.get("batch_id"))
    response.status_code = status
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return payload


@router.get("/batches/{batch_id}", tags=["batches"], response_model=BatchResultResponse, summary="Batch result")
def batch_detail(
    batch_id: uuid.UUID, request: Request, db: Session = Depends(get_db), actor: Actor = Depends(require("audit.read"))
) -> dict[str, Any]:
    tag(request, batch_id=batch_id)
    return batch_service.get(db, actor, batch_id)


@router.post(
    "/demo-sessions", tags=["demo-sessions"], status_code=201, response_model=DemoSessionResponse, summary="Create demo session"
)
def create_demo_session(
    request: Request,
    body: DemoSessionCreate | None = None,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require("decision.accept")),
) -> dict[str, Any]:
    return decision_service.create_session(db, actor, body.name if body else None, correlation_id(request))


@router.get(
    "/demo-sessions/{demo_session_id}", tags=["demo-sessions"], response_model=DemoSessionResponse, summary="Demo session"
)
def get_demo_session(
    demo_session_id: uuid.UUID, db: Session = Depends(get_db), actor: Actor = Depends(require("snapshot.read"))
) -> dict[str, Any]:
    return decision_service.get_session(db, actor, demo_session_id)


@router.get("/demo-sessions/{demo_session_id}/decisions", tags=["demo-sessions"], summary="Decisions of a demo session")
def demo_session_decisions(
    demo_session_id: uuid.UUID,
    snapshot_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    actor: Actor = Depends(require("snapshot.read")),
) -> dict[str, Any]:
    decision_service.get_session(db, actor, demo_session_id)
    return decision_service.list_decisions(
        db,
        actor_id=None,
        demo_session_id=demo_session_id,
        snapshot_id=snapshot_id,
        proposal_id=None,
        hex_id=None,
        action=None,
        cursor=cursor,
        limit=limit,
    )


@router.get("/audit-events", tags=["audit"], summary="Append-only audit log")
def audit_events(
    demo_session_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor_id: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: Actor = Depends(require("audit.read")),
) -> dict[str, Any]:
    return audit_service.list_events(
        db,
        demo_session_id=demo_session_id,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        from_ts=aware(from_ts),
        to_ts=aware(to_ts),
        cursor=cursor,
        limit=limit,
    )
