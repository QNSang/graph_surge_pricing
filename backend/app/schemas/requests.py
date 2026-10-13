"""Request bodies (spec §9). Surge values are decimal strings; actor never comes from the body."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DECIMAL_PATTERN = r"^-?\d+(\.\d+)?$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DecisionRequest(_Strict):
    schema_version: Literal["surge-decision.v1"] = "surge-decision.v1"
    demo_session_id: uuid.UUID
    idempotency_key: str = Field(min_length=1, max_length=200)
    proposal_id: str = Field(min_length=1)
    expected_proposal_version: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    action: Literal["ACCEPT_PROPOSAL", "KEEP_BIDDING", "OVERRIDE_PROPOSAL"]
    requested_surge: str | None = Field(default=None, pattern=DECIMAL_PATTERN)
    reason: str | None = Field(default=None, max_length=1000)
    recommendation_set_id: str | None = None
    expected_policy_version: str | None = None

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "schema_version": "surge-decision.v1",
                    "demo_session_id": "00000000-0000-0000-0000-000000000000",
                    "idempotency_key": "intent_001",
                    "proposal_id": "prop_xxx",
                    "expected_proposal_version": "1",
                    "snapshot_id": "snap_xxx",
                    "action": "OVERRIDE_PROPOSAL",
                    "requested_surge": "1.30",
                    "reason": "Manual adjustment by operator",
                }
            ]
        },
    )


class BatchPreviewRequest(_Strict):
    demo_session_id: uuid.UUID
    snapshot_id: str
    recommendation_set_id: str
    selection_mode: Literal["ALL_ELIGIBLE", "SELECTED"]
    proposal_ids: list[str] | None = Field(default=None, max_length=1000)


class BatchCommitRequest(_Strict):
    demo_session_id: uuid.UUID
    batch_plan_id: uuid.UUID
    idempotency_key: str = Field(min_length=1, max_length=200)


class DemoSessionCreate(_Strict):
    name: str | None = Field(default=None, max_length=200)
