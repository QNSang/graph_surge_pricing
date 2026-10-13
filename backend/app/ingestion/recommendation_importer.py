"""Provider -> validation -> publish an immutable recommendation set (spec §4.6). Idempotent by content hash."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Policy
from app.db.models import (
    DatasetRelease,
    Hex,
    HexMarketState,
    PolicyConfig,
    ProviderMetadata,
    Recommendation,
    RecommendationSet,
    Snapshot,
)
from app.domain.enums import RecommendationSetStatus
from app.domain.policies import fmt
from app.providers.base import HexInput, RecommendationBatch, RecommendationProvider, SnapshotInput
from app.services.validation_service import ValidationReport, json_safe, validate_batch


@dataclass
class ImportResult:
    snapshot_id: str
    recommendation_set_id: str | None
    status: str
    created: bool
    summary: dict


def register_policy(session: Session, policy: Policy) -> None:
    session.execute(
        insert(PolicyConfig)
        .values(policy_version=policy.policy_version, config=policy.as_public_dict())
        .on_conflict_do_nothing(index_elements=["policy_version"])
    )


def register_provider(session: Session, provider: RecommendationProvider) -> None:
    info = provider.info
    stmt = insert(ProviderMetadata).values(
        provider_id=info.id, kind=info.kind, description=info.description, latest_version=info.version
    )
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["provider_id"],
            set_={"latest_version": stmt.excluded.latest_version, "description": stmt.excluded.description},
        )
    )


def build_snapshot_input(session: Session, snapshot: Snapshot, policy: Policy) -> SnapshotInput:
    release = session.get(DatasetRelease, snapshot.dataset_id)
    rows = session.execute(
        select(HexMarketState, Hex.neighbors)
        .join(Hex, Hex.hex_id == HexMarketState.hex_id)
        .where(HexMarketState.snapshot_id == snapshot.snapshot_id)
        .order_by(Hex.node_index)
    ).all()
    hexes = tuple(
        HexInput(
            hex_id=m.hex_id,
            neighbors=tuple(neighbors or ()),
            demand=m.demand,
            idle_supply=m.idle_supply,
            effective_supply=m.effective_supply,
            observed_ds=m.observed_ds,
            surge_base=fmt(m.surge_base),
        )
        for m, neighbors in rows
    )
    return SnapshotInput(
        snapshot_id=snapshot.snapshot_id,
        dataset_id=snapshot.dataset_id,
        dataset_fingerprint=release.fingerprint,
        region_id=snapshot.region_id,
        cutoff_ts=snapshot.cutoff_ts,
        policy_version=policy.policy_version,
        hexes=hexes,
    )


def content_hash(batch: RecommendationBatch) -> str:
    """Hash of the provider payload excluding generated_at, so a re-run with identical output is a no-op."""
    payload = {
        "schema_version": batch.schema_version,
        "snapshot_id": batch.snapshot_id,
        "provider": [batch.provider.id, batch.provider.version],
        "policy_version": batch.policy_version,
        "recommendations": json_safe(batch.recommendations),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _short(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def persist_batch(session: Session, batch: RecommendationBatch, report: ValidationReport, snapshot_id: str) -> ImportResult:
    chash = content_hash(batch)
    existing = session.scalar(
        select(RecommendationSet).where(
            RecommendationSet.snapshot_id == snapshot_id,
            RecommendationSet.provider_id == batch.provider.id,
            RecommendationSet.provider_version == batch.provider.version,
            RecommendationSet.content_hash == chash,
        )
    )
    if existing is not None:
        return ImportResult(snapshot_id, existing.recommendation_set_id, existing.status, False, existing.validation_summary)

    set_id = "rs_" + _short(snapshot_id, batch.provider.id, batch.provider.version, chash)
    status = RecommendationSetStatus.PUBLISHED if report.publishable else RecommendationSetStatus.REJECTED
    summary = report.summary()
    session.add(
        RecommendationSet(
            recommendation_set_id=set_id,
            snapshot_id=snapshot_id,
            provider_id=batch.provider.id,
            provider_version=batch.provider.version,
            policy_version=batch.policy_version,
            output_contract_version=batch.schema_version,
            generated_at=batch.generated_at,
            dataset_fingerprint=batch.dataset_fingerprint or "",
            content_hash=chash,
            model_metadata=json_safe(batch.model_metadata),
            validation_summary=summary,
            status=status.value,
        )
    )
    session.flush()
    if report.publishable:
        session.add_all(
            Recommendation(
                proposal_id="prop_" + _short(set_id, row.hex_id),
                recommendation_set_id=set_id,
                snapshot_id=snapshot_id,
                hex_id=row.hex_id,
                provider_proposal_id=row.provider_proposal_id,
                proposal_version="1",
                action=row.action,
                surge_base=row.surge_base,
                surge_delta=row.surge_delta,
                surge_proposed=row.surge_proposed,
                explanation=row.explanation,
                reason_codes=row.reason_codes,
                evidence=row.evidence,
                policy_version=batch.policy_version,
                validation_status=row.validation_status,
                validation_errors=row.validation_errors,
            )
            for row in report.rows
        )
    return ImportResult(snapshot_id, set_id, status.value, True, summary)


def import_recommendations(
    session: Session, snapshot: Snapshot, provider: RecommendationProvider, policy: Policy
) -> ImportResult:
    snap_input = build_snapshot_input(session, snapshot, policy)
    batch = provider.generate(snap_input)
    report = validate_batch(
        batch,
        snapshot_id=snapshot.snapshot_id,
        snapshot_hexes={h.hex_id for h in snap_input.hexes},
        dataset_fingerprint=snap_input.dataset_fingerprint,
        policy=policy,
    )
    result = persist_batch(session, batch, report, snapshot.snapshot_id)
    session.commit()
    return result
