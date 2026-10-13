"""Queries over published recommendation sets and recommendations (immutable after publish)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ProviderMetadata, Recommendation, RecommendationSet
from app.domain.enums import RecommendationSetStatus


def latest_published_set(session: Session, snapshot_id: str) -> RecommendationSet | None:
    """The current set of a snapshot = most recently published one; older sets are SUPERSEDED."""
    return session.scalar(
        select(RecommendationSet)
        .where(
            RecommendationSet.snapshot_id == snapshot_id,
            RecommendationSet.status == RecommendationSetStatus.PUBLISHED.value,
        )
        .order_by(RecommendationSet.created_at.desc(), RecommendationSet.recommendation_set_id.desc())
        .limit(1)
    )


def get_set(session: Session, set_id: str) -> RecommendationSet | None:
    return session.get(RecommendationSet, set_id)


def sets_for_snapshot(session: Session, snapshot_id: str) -> list[RecommendationSet]:
    return list(
        session.scalars(
            select(RecommendationSet)
            .where(RecommendationSet.snapshot_id == snapshot_id)
            .order_by(RecommendationSet.created_at.desc())
        )
    )


def for_set(session: Session, set_id: str, *, action: str | None = None, hex_id: str | None = None) -> list[Recommendation]:
    q = select(Recommendation).where(Recommendation.recommendation_set_id == set_id)
    if action:
        q = q.where(Recommendation.action == action)
    if hex_id:
        q = q.where(Recommendation.hex_id == hex_id)
    return list(session.scalars(q.order_by(Recommendation.hex_id)))


def get(session: Session, proposal_id: str, *, for_update: bool = False) -> Recommendation | None:
    q = select(Recommendation).where(Recommendation.proposal_id == proposal_id)
    if for_update:
        q = q.with_for_update()
    return session.scalar(q)


def get_many(session: Session, proposal_ids: list[str]) -> list[Recommendation]:
    if not proposal_ids:
        return []
    return list(session.scalars(select(Recommendation).where(Recommendation.proposal_id.in_(proposal_ids))))


def providers(session: Session) -> list[ProviderMetadata]:
    return list(session.scalars(select(ProviderMetadata).order_by(ProviderMetadata.provider_id)))
