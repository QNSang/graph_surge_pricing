"""Read APIs: snapshots, recommendations, geography, providers, policy, history (spec §8.2–8.4, §12)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import aware, policy_dep, tag
from app.core.config import Policy, get_settings
from app.core.security import Actor, require
from app.db.session import get_db
from app.domain.timefmt import iso
from app.repositories import recommendation_repository
from app.schemas.responses import ERROR_RESPONSES
from app.services import recommendation_service, replay_service, snapshot_service

router = APIRouter(responses=ERROR_RESPONSES)

ActionFilter = Literal["INCREASE", "DECREASE", "HOLD", "REVIEW"]
EligibilityFilter = Literal["ELIGIBLE", "BLOCKED", "EXPIRED", "SUPERSEDED", "UNKNOWN"]
DecisionFilter = Literal["UNDECIDED", "RECORDED", "KEPT_BIDDING"]


@router.get("/snapshots", tags=["snapshots"], summary="List snapshots (cursor pagination)")
def list_snapshots(
    region_id: str | None = None,
    dataset_id: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: Actor = Depends(require("snapshot.read")),
) -> dict[str, Any]:
    return snapshot_service.list_snapshots(
        db,
        region_id=region_id,
        dataset_id=dataset_id,
        from_ts=aware(from_ts),
        to_ts=aware(to_ts),
        cursor=cursor,
        limit=limit,
    )


@router.get("/snapshots/{snapshot_id}", tags=["snapshots"], summary="Snapshot detail")
def snapshot_detail(
    snapshot_id: str, request: Request, db: Session = Depends(get_db), _: Actor = Depends(require("snapshot.read"))
) -> dict[str, Any]:
    tag(request, snapshot_id=snapshot_id)
    return snapshot_service.detail(db, snapshot_id)


@router.get("/snapshots/{snapshot_id}/recommendations", tags=["recommendations"], summary="Recommendations of a snapshot")
def snapshot_recommendations(
    snapshot_id: str,
    request: Request,
    action: ActionFilter | None = None,
    eligibility: EligibilityFilter | None = None,
    decision_status: DecisionFilter | None = Query(None, description="Requires demo_session_id"),
    hex_id: str | None = None,
    recommendation_set_id: str | None = None,
    demo_session_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    policy: Policy = Depends(policy_dep),
    _: Actor = Depends(require("recommendation.read")),
) -> dict[str, Any]:
    tag(request, snapshot_id=snapshot_id, demo_session_id=demo_session_id)
    return recommendation_service.list_for_snapshot(
        db,
        snapshot_id,
        policy,
        action=action,
        eligibility=eligibility,
        decision_status=decision_status,
        hex_id=hex_id,
        set_id=recommendation_set_id,
        demo_session_id=demo_session_id,
    )


@router.get("/snapshots/{snapshot_id}/summary", tags=["snapshots"], summary="Action / eligibility / decision counts")
def snapshot_summary(
    snapshot_id: str,
    request: Request,
    demo_session_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    policy: Policy = Depends(policy_dep),
    _: Actor = Depends(require("recommendation.read")),
) -> dict[str, Any]:
    tag(request, snapshot_id=snapshot_id, demo_session_id=demo_session_id)
    return snapshot_service.summary(db, snapshot_id, policy, demo_session_id)


@router.get(
    "/snapshots/{snapshot_id}/read-model",
    tags=["snapshots"],
    summary="Unified map + queue + panel read model for one snapshot identity",
)
def snapshot_read_model(
    snapshot_id: str,
    request: Request,
    demo_session_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    policy: Policy = Depends(policy_dep),
    _: Actor = Depends(require("recommendation.read")),
) -> dict[str, Any]:
    tag(request, snapshot_id=snapshot_id, demo_session_id=demo_session_id)
    return snapshot_service.read_model(db, snapshot_id, policy, demo_session_id)


@router.get("/regions/{region_id}/hexes", tags=["snapshots"], summary="Hex geography of a region")
def region_hexes(
    region_id: str, db: Session = Depends(get_db), _: Actor = Depends(require("snapshot.read"))
) -> dict[str, Any]:
    return snapshot_service.region_hexes(db, region_id)


@router.get("/recommendations/{proposal_id}", tags=["recommendations"], summary="Proposal detail")
def recommendation_detail(
    proposal_id: str,
    request: Request,
    demo_session_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    policy: Policy = Depends(policy_dep),
    _: Actor = Depends(require("recommendation.read")),
) -> dict[str, Any]:
    tag(request, proposal_id=proposal_id, demo_session_id=demo_session_id)
    return recommendation_service.detail(db, proposal_id, policy, demo_session_id)


@router.get("/providers", tags=["recommendations"], summary="Provider metadata")
def providers(db: Session = Depends(get_db), _: Actor = Depends(require("recommendation.read"))) -> dict[str, Any]:
    return {
        "items": [
            {
                "provider_id": p.provider_id,
                "kind": p.kind,
                "description": p.description,
                "latest_version": p.latest_version,
                "metadata": p.metadata_,
                "registered_at": iso(p.registered_at),
            }
            for p in recommendation_repository.providers(db)
        ]
    }


@router.get("/policies/current", tags=["recommendations"], summary="Read-only policy metadata")
def current_policy(policy: Policy = Depends(policy_dep), _: Actor = Depends(require("recommendation.read"))) -> dict[str, Any]:
    return {**policy.as_public_dict(), "region_id": policy.region_id, "region_label": policy.region_label}


@router.get("/hexes/{hex_id}/history", tags=["history"], summary="Market history series of one hex")
def hex_history(
    hex_id: str,
    series: Literal["BASE_BIDDING", "DEMAND", "EFFECTIVE_SUPPLY", "OBSERVED_DS", "FORECAST_DS"] = "BASE_BIDDING",
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    dataset_id: str | None = None,
    region_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(288, ge=1, le=5000),
    db: Session = Depends(get_db),
    _: Actor = Depends(require("snapshot.read")),
) -> dict[str, Any]:
    return replay_service.history(
        db,
        hex_id=hex_id,
        series=series,
        from_ts=aware(from_ts),
        to_ts=aware(to_ts),
        dataset_id=dataset_id,
        region_id=region_id,
        cursor=cursor,
        limit=limit,
        timezone=get_settings().timezone,
    )
