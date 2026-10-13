"""Response models for the mutation endpoints and the error envelope (spec §9, §10.1)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any]
    correlation_id: str | None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ProviderRef(BaseModel):
    id: str
    version: str


class DecisionResponse(BaseModel):
    decision_id: str
    demo_session_id: str
    proposal_id: str
    proposal_version: str
    snapshot_id: str
    recommendation_set_id: str
    hex_id: str
    action: str
    status: str
    surge_base: str | None
    surge_proposed: str | None
    requested_surge: str | None
    surge_decided: str | None
    reason: str | None
    actor_id: str
    batch_id: str | None
    provider: ProviderRef
    policy_version: str
    execution_mode: str
    production_effective: bool
    created_at: str | None
    recorded_at: str | None


class BatchPreviewItem(BaseModel):
    proposal_id: str
    proposal_version: str
    hex_id: str
    action: str
    surge_base: str | None
    surge_proposed: str | None
    eligible: bool
    reason_code: str | None = None


class BatchPreviewResponse(BaseModel):
    batch_plan_id: str
    demo_session_id: str
    snapshot_id: str
    recommendation_set_id: str
    selection_mode: str
    total_candidates: int
    eligible_count: int
    skipped_count: int
    items: list[BatchPreviewItem]
    expires_at: str


class BatchItemResult(BaseModel):
    proposal_id: str
    proposal_version: str
    status: str
    decision_id: str | None
    error_code: str | None
    error_message: str | None


class BatchResultResponse(BaseModel):
    batch_id: str
    batch_plan_id: str
    demo_session_id: str
    snapshot_id: str
    recommendation_set_id: str
    status: str
    total: int
    succeeded: int
    failed: int
    execution_mode: str
    production_effective: bool
    created_at: str | None
    completed_at: str | None
    results: list[BatchItemResult]


class DemoSessionResponse(BaseModel):
    demo_session_id: str
    actor_id: str
    name: str
    status: str
    execution_mode: str
    metadata: dict[str, Any]
    created_at: str | None


ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}
