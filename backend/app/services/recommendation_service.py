"""Recommendation read side: current-set selection, server-side eligibility and per-session decision state."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Policy
from app.core.errors import AppError
from app.db.models import Decision, Recommendation, RecommendationSet
from app.domain.policies import EligibilityResult, evaluate_eligibility, fmt
from app.domain.timefmt import iso
from app.repositories import decision_repository, recommendation_repository, snapshot_repository

DECISION_FILTERS = ("UNDECIDED", "RECORDED", "KEPT_BIDDING")


@dataclass
class ProposalView:
    rec: Recommendation
    rset: RecommendationSet
    eligibility: EligibilityResult
    decision: Decision | None


def evaluate(rec: Recommendation, current_set_id: str | None, policy: Policy) -> EligibilityResult:
    return evaluate_eligibility(
        action=rec.action,
        validation_status=rec.validation_status,
        surge_base=rec.surge_base,
        surge_proposed=rec.surge_proposed,
        rec_policy_version=rec.policy_version,
        superseded=current_set_id is not None and rec.recommendation_set_id != current_set_id,
        policy=policy,
    )


def capabilities(view: ProposalView) -> dict[str, bool]:
    if view.decision is not None:
        return {k: False for k in view.eligibility.capabilities}
    return dict(view.eligibility.capabilities)


def serialize_decision_brief(d: Decision | None) -> dict | None:
    if d is None:
        return None
    return {
        "decision_id": str(d.decision_id),
        "action": d.action,
        "status": d.status,
        "surge_decided": fmt(d.surge_decided),
        "actor_id": d.actor_id,
        "batch_id": str(d.batch_id) if d.batch_id else None,
        "recorded_at": iso(d.recorded_at),
    }


def serialize(view: ProposalView) -> dict:
    rec, rset = view.rec, view.rset
    reasons = list(view.eligibility.blocked_reasons)
    if view.decision is not None:
        reasons.append("DECISION_ALREADY_EXISTS")
    return {
        "proposal_id": rec.proposal_id,
        "proposal_version": rec.proposal_version,
        "provider_proposal_id": rec.provider_proposal_id,
        "recommendation_set_id": rec.recommendation_set_id,
        "snapshot_id": rec.snapshot_id,
        "hex_id": rec.hex_id,
        "action": rec.action,
        "surge_base": fmt(rec.surge_base),
        "surge_delta": fmt(rec.surge_delta),
        "surge_proposed": fmt(rec.surge_proposed),
        "explanation": rec.explanation,
        "reason_codes": rec.reason_codes,
        "evidence": rec.evidence,
        "provider": {"id": rset.provider_id, "version": rset.provider_version},
        "policy_version": rec.policy_version,
        "validation": {"status": rec.validation_status, "errors": rec.validation_errors},
        "eligibility": {"state": view.eligibility.state.value, "reasons": reasons},
        "capabilities": capabilities(view),
        "decision": serialize_decision_brief(view.decision),
    }


def serialize_set(rset: RecommendationSet | None, current_id: str | None) -> dict | None:
    if rset is None:
        return None
    return {
        "recommendation_set_id": rset.recommendation_set_id,
        "snapshot_id": rset.snapshot_id,
        "provider": {"id": rset.provider_id, "version": rset.provider_version},
        "policy_version": rset.policy_version,
        "output_contract_version": rset.output_contract_version,
        "dataset_fingerprint": rset.dataset_fingerprint,
        "status": rset.status,
        "is_current": rset.recommendation_set_id == current_id,
        "generated_at": iso(rset.generated_at),
        "created_at": iso(rset.created_at),
        "model_metadata": rset.model_metadata,
        "validation_summary": rset.validation_summary,
    }


def resolve_set(session: Session, snapshot_id: str, set_id: str | None) -> tuple[RecommendationSet | None, str | None]:
    """Return (selected set, current set id). An explicit set must belong to the snapshot."""
    current = recommendation_repository.latest_published_set(session, snapshot_id)
    current_id = current.recommendation_set_id if current else None
    if set_id is None:
        return current, current_id
    rset = recommendation_repository.get_set(session, set_id)
    if rset is None or rset.snapshot_id != snapshot_id:
        raise AppError(
            "RECOMMENDATION_SET_MISMATCH",
            "Recommendation set does not belong to this snapshot.",
            {"snapshot_id": snapshot_id, "recommendation_set_id": set_id},
        )
    return rset, current_id


def views_for_snapshot(
    session: Session,
    snapshot_id: str,
    policy: Policy,
    *,
    set_id: str | None = None,
    demo_session_id: uuid.UUID | None = None,
    action: str | None = None,
    hex_id: str | None = None,
) -> tuple[RecommendationSet | None, str | None, list[ProposalView]]:
    rset, current_id = resolve_set(session, snapshot_id, set_id)
    if rset is None:
        return None, None, []
    recs = recommendation_repository.for_set(session, rset.recommendation_set_id, action=action, hex_id=hex_id)
    finals = decision_repository.finals_by_proposal(session, demo_session_id, snapshot_id) if demo_session_id else {}
    views = [ProposalView(r, rset, evaluate(r, current_id, policy), finals.get(r.proposal_id)) for r in recs]
    return rset, current_id, views


def list_for_snapshot(
    session: Session,
    snapshot_id: str,
    policy: Policy,
    *,
    action: str | None,
    eligibility: str | None,
    decision_status: str | None,
    hex_id: str | None,
    set_id: str | None,
    demo_session_id: uuid.UUID | None,
) -> dict:
    if snapshot_repository.get(session, snapshot_id) is None:
        raise AppError("SNAPSHOT_NOT_FOUND", "Snapshot not found.", {"snapshot_id": snapshot_id})
    if decision_status and demo_session_id is None:
        raise AppError("INVALID_REQUEST", "decision_status filter requires demo_session_id.")
    if decision_status and decision_status not in DECISION_FILTERS:
        raise AppError("INVALID_REQUEST", "Unknown decision_status.", {"allowed": list(DECISION_FILTERS)})
    rset, current_id, views = views_for_snapshot(
        session, snapshot_id, policy, set_id=set_id, demo_session_id=demo_session_id, action=action, hex_id=hex_id
    )
    if eligibility:
        views = [v for v in views if v.eligibility.state.value == eligibility]
    if decision_status == "UNDECIDED":
        views = [v for v in views if v.decision is None]
    elif decision_status:
        views = [v for v in views if v.decision is not None and v.decision.status == decision_status]
    return {
        "snapshot_id": snapshot_id,
        "recommendation_set": serialize_set(rset, current_id),
        "demo_session_id": str(demo_session_id) if demo_session_id else None,
        "total": len(views),
        "items": [serialize(v) for v in views],
    }


def detail(session: Session, proposal_id: str, policy: Policy, demo_session_id: uuid.UUID | None) -> dict:
    rec = recommendation_repository.get(session, proposal_id)
    if rec is None:
        raise AppError("PROPOSAL_NOT_FOUND", "Proposal not found.", {"proposal_id": proposal_id})
    rset = recommendation_repository.get_set(session, rec.recommendation_set_id)
    current = recommendation_repository.latest_published_set(session, rec.snapshot_id)
    decision = decision_repository.final_decision(session, demo_session_id, proposal_id) if demo_session_id else None
    view = ProposalView(rec, rset, evaluate(rec, current.recommendation_set_id if current else None, policy), decision)
    market = snapshot_repository.market_state(session, rec.snapshot_id, rec.hex_id)
    out = serialize(view)
    out["limits"] = policy.as_public_dict()["surge_limits"]
    out["market"] = serialize_market(market) if market else None
    return out


def serialize_market(m) -> dict:
    return {
        "demand": m.demand,
        "idle_supply": m.idle_supply,
        "effective_supply": m.effective_supply,
        "observed_ds": m.observed_ds,
        "surge_base": fmt(m.surge_base),
        "bidding_source_version": m.bidding_source_version,
        "null_reasons": m.null_reasons,
    }
