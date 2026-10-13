"""ORM tables (spec §11). Published source entities are immutable; decisions/batches follow a lifecycle."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


ACTIONS = ("INCREASE", "DECREASE", "HOLD", "REVIEW")
DECISION_ACTIONS = ("ACCEPT_PROPOSAL", "KEEP_BIDDING", "OVERRIDE_PROPOSAL")
DECISION_STATUSES = ("RECORDED", "KEPT_BIDDING")
BATCH_STATUSES = ("PROCESSING", "SUCCESS", "PARTIAL_SUCCESS", "FAILED")
BATCH_ITEM_STATUSES = ("PENDING", "SUCCESS", "FAILED")

TSTZ = DateTime(timezone=True)


class DatasetRelease(Base):
    __tablename__ = "dataset_releases"

    dataset_id: Mapped[str] = mapped_column(Text, primary_key=True)
    dataset_name: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_version: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=func.now())


class Hex(Base):
    """Shared geography; polygons do not change between snapshots of one node mapping."""

    __tablename__ = "hexes"

    hex_id: Mapped[str] = mapped_column(Text, primary_key=True)
    region_id: Mapped[str] = mapped_column(Text, nullable=False)
    node_mapping_version: Mapped[str] = mapped_column(Text, nullable=False)
    node_index: Mapped[int] = mapped_column(Integer, nullable=False)
    zone: Mapped[str | None] = mapped_column(Text)
    ring: Mapped[int | None] = mapped_column(Integer)
    lat: Mapped[float] = mapped_column(Double, nullable=False)
    lng: Mapped[float] = mapped_column(Double, nullable=False)
    polygon: Mapped[list] = mapped_column(JSONB, nullable=False)
    neighbors: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))

    __table_args__ = (Index("ix_hexes_region", "region_id", "node_index"),)


class Snapshot(Base):
    __tablename__ = "snapshots"

    snapshot_id: Mapped[str] = mapped_column(Text, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("dataset_releases.dataset_id", ondelete="RESTRICT"), nullable=False)
    region_id: Mapped[str] = mapped_column(Text, nullable=False)
    cutoff_ts: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    forecast_ts: Mapped[datetime | None] = mapped_column(TSTZ)
    node_mapping_version: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_version: Mapped[str] = mapped_column(Text, nullable=False, server_default="1")
    data_kind: Mapped[str] = mapped_column(Text, nullable=False)
    hex_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("dataset_id", "region_id", "cutoff_ts", "node_mapping_version", name="uq_snapshot_identity"),
        CheckConstraint(_in("data_kind", ("SYNTHETIC", "HISTORICAL", "LIVE")), name="ck_snapshot_data_kind"),
        Index("ix_snapshots_cutoff", "cutoff_ts"),
    )


class HexMarketState(Base):
    __tablename__ = "hex_market_states"

    snapshot_id: Mapped[str] = mapped_column(ForeignKey("snapshots.snapshot_id", ondelete="RESTRICT"), nullable=False)
    hex_id: Mapped[str] = mapped_column(ForeignKey("hexes.hex_id", ondelete="RESTRICT"), nullable=False)
    # Denormalised from snapshots for per-hex history range scans.
    cutoff_ts: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    demand: Mapped[float | None] = mapped_column(Double)
    idle_supply: Mapped[float | None] = mapped_column(Double)
    effective_supply: Mapped[float | None] = mapped_column(Double)
    observed_ds: Mapped[float | None] = mapped_column(Double)
    surge_base: Mapped[Decimal | None] = mapped_column(Numeric)
    bidding_source_version: Mapped[str | None] = mapped_column(Text)
    null_reasons: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    market_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    __table_args__ = (
        PrimaryKeyConstraint("snapshot_id", "hex_id", name="pk_hex_market_states"),
        Index("ix_market_hex_cutoff", "hex_id", "cutoff_ts"),
    )


class ProviderMetadata(Base):
    __tablename__ = "provider_metadata"

    provider_id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    latest_version: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    registered_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=func.now())


class PolicyConfig(Base):
    __tablename__ = "policy_configs"

    policy_version: Mapped[str] = mapped_column(Text, primary_key=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=func.now())


class RecommendationSet(Base):
    __tablename__ = "recommendation_sets"

    recommendation_set_id: Mapped[str] = mapped_column(Text, primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("snapshots.snapshot_id", ondelete="RESTRICT"), nullable=False)
    provider_id: Mapped[str] = mapped_column(ForeignKey("provider_metadata.provider_id"), nullable=False)
    provider_version: Mapped[str] = mapped_column(Text, nullable=False)
    policy_version: Mapped[str] = mapped_column(Text, nullable=False)
    output_contract_version: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    dataset_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    model_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    validation_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("snapshot_id", "provider_id", "provider_version", "content_hash", name="uq_recset_content"),
        CheckConstraint(_in("status", ("PUBLISHED", "REJECTED")), name="ck_recset_status"),
        Index("ix_recsets_snapshot", "snapshot_id", "created_at"),
        Index("ix_recsets_provider", "provider_id"),
    )


class Recommendation(Base):
    __tablename__ = "recommendations"

    proposal_id: Mapped[str] = mapped_column(Text, primary_key=True)
    recommendation_set_id: Mapped[str] = mapped_column(
        ForeignKey("recommendation_sets.recommendation_set_id", ondelete="RESTRICT"), nullable=False
    )
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("snapshots.snapshot_id", ondelete="RESTRICT"), nullable=False)
    hex_id: Mapped[str] = mapped_column(ForeignKey("hexes.hex_id"), nullable=False)
    provider_proposal_id: Mapped[str | None] = mapped_column(Text)
    proposal_version: Mapped[str] = mapped_column(Text, nullable=False, server_default="1")
    action: Mapped[str] = mapped_column(Text, nullable=False)
    surge_base: Mapped[Decimal | None] = mapped_column(Numeric)
    surge_delta: Mapped[Decimal | None] = mapped_column(Numeric)
    surge_proposed: Mapped[Decimal | None] = mapped_column(Numeric)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    reason_codes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    policy_version: Mapped[str] = mapped_column(Text, nullable=False)
    validation_status: Mapped[str] = mapped_column(Text, nullable=False)
    validation_errors: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("recommendation_set_id", "hex_id", name="uq_recommendation_set_hex"),
        CheckConstraint(_in("action", ACTIONS), name="ck_recommendation_action"),
        CheckConstraint(_in("validation_status", ("VALID", "INVALID")), name="ck_recommendation_validation"),
        CheckConstraint(
            "validation_status = 'INVALID' OR surge_base IS NOT NULL", name="ck_recommendation_valid_has_base"
        ),
        Index("ix_recommendations_snapshot_action", "snapshot_id", "action"),
        Index("ix_recommendations_hex", "hex_id"),
    )


class DemoSession(Base):
    __tablename__ = "demo_sessions"

    demo_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="ACTIVE")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(_in("status", ("ACTIVE", "CLOSED")), name="ck_demo_session_status"),
        Index("ix_demo_sessions_actor", "actor_id", "created_at"),
    )


class Decision(Base):
    __tablename__ = "decisions"

    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    demo_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("demo_sessions.demo_session_id", ondelete="RESTRICT"), nullable=False
    )
    proposal_id: Mapped[str] = mapped_column(ForeignKey("recommendations.proposal_id", ondelete="RESTRICT"), nullable=False)
    proposal_version: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("snapshots.snapshot_id", ondelete="RESTRICT"), nullable=False)
    recommendation_set_id: Mapped[str] = mapped_column(Text, nullable=False)
    hex_id: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    surge_base: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    surge_proposed: Mapped[Decimal | None] = mapped_column(Numeric)
    requested_surge: Mapped[Decimal | None] = mapped_column(Numeric)
    surge_decided: Mapped[Decimal | None] = mapped_column(Numeric)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    policy_version: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_version: Mapped[str] = mapped_column(Text, nullable=False)
    execution_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="DEMO")
    created_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=func.now())
    recorded_at: Mapped[datetime | None] = mapped_column(TSTZ)

    __table_args__ = (
        CheckConstraint(_in("action", DECISION_ACTIONS), name="ck_decision_action"),
        CheckConstraint(_in("status", DECISION_STATUSES), name="ck_decision_status"),
        CheckConstraint("execution_mode = 'DEMO'", name="ck_decision_demo_only"),
        # One final successful decision per proposal per demo session (spec §6.6, BE-13).
        Index(
            "uq_decision_final_per_session",
            "demo_session_id",
            "proposal_id",
            unique=True,
            postgresql_where=text("status IN ('RECORDED', 'KEPT_BIDDING')"),
        ),
        Index("ix_decisions_actor_created", "actor_id", "created_at"),
        Index("ix_decisions_proposal", "proposal_id"),
        Index("ix_decisions_snapshot", "snapshot_id"),
        Index("ix_decisions_session_created", "demo_session_id", "created_at"),
    )


class BatchPlan(Base):
    __tablename__ = "batch_plans"

    batch_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    demo_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("demo_sessions.demo_session_id", ondelete="RESTRICT"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("snapshots.snapshot_id"), nullable=False)
    recommendation_set_id: Mapped[str] = mapped_column(
        ForeignKey("recommendation_sets.recommendation_set_id"), nullable=False
    )
    selection_mode: Mapped[str] = mapped_column(Text, nullable=False)
    items: Mapped[list] = mapped_column(JSONB, nullable=False)
    skipped: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("selection_mode", ("ALL_ELIGIBLE", "SELECTED")), name="ck_batch_plan_mode"),
        Index("ix_batch_plans_session", "demo_session_id", "created_at"),
    )


class DecisionBatch(Base):
    __tablename__ = "decision_batches"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    batch_plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("batch_plans.batch_plan_id"), nullable=False)
    demo_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("demo_sessions.demo_session_id", ondelete="RESTRICT"), nullable=False
    )
    snapshot_id: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation_set_id: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(TSTZ)

    __table_args__ = (
        # A frozen plan is committed at most once; a retry resumes the same batch (spec §7.7).
        UniqueConstraint("batch_plan_id", name="uq_batch_per_plan"),
        CheckConstraint(_in("status", BATCH_STATUSES), name="ck_batch_status"),
        Index("ix_batches_session_created", "demo_session_id", "created_at"),
    )


class DecisionBatchItem(Base):
    __tablename__ = "decision_batch_items"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("decision_batches.batch_id", ondelete="RESTRICT"), nullable=False
    )
    proposal_id: Mapped[str] = mapped_column(Text, nullable=False)
    proposal_version: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_action: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("decisions.decision_id"))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=func.now())

    __table_args__ = (
        PrimaryKeyConstraint("batch_id", "proposal_id", name="pk_decision_batch_items"),
        CheckConstraint(_in("status", BATCH_ITEM_STATUSES), name="ck_batch_item_status"),
        Index("ix_batch_items_decision", "decision_id"),
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    http_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),
        Index("ix_idempotency_actor_key", "actor_id", "key"),
    )


class AuditEvent(Base):
    """Append-only: a DB trigger rejects UPDATE/DELETE (migration 0001)."""

    __tablename__ = "audit_events"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    demo_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    previous_state: Mapped[dict | None] = mapped_column(JSONB)
    new_state: Mapped[dict | None] = mapped_column(JSONB)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    correlation_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=func.now())
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("nextval('audit_events_seq')"))

    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id", "created_at"),
        Index("ix_audit_session_seq", "demo_session_id", "seq"),
        Index("ix_audit_seq", "seq"),
    )


__all__ = [
    "AuditEvent",
    "BatchPlan",
    "DatasetRelease",
    "Decision",
    "DecisionBatch",
    "DecisionBatchItem",
    "DemoSession",
    "Hex",
    "HexMarketState",
    "IdempotencyRecord",
    "PolicyConfig",
    "ProviderMetadata",
    "Recommendation",
    "RecommendationSet",
]
