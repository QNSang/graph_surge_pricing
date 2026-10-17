from __future__ import annotations
from datetime import timedelta
from typing import Annotated, Literal
from pydantic import AwareDatetime, Field, model_validator
from .common import Contract, TestOnly, Name, Nodes, NonNegative

class Identity(TestOnly):
    snapshot_id: Name
    decision_id: Name
    dataset_id: Name
    dataset_fingerprint: Name
    node_mapping_version: Name
    feature_version: Name
    reference_policy_version: Name
    semantic_profile_id: Literal["ggso.confirmed-bookings.eligible-idle.h5.test.v2"]
    cutoff_time: AwareDatetime
    target_time: AwareDatetime
    required_hex_ids: Nodes
    horizon_minutes: Literal[5]

    @model_validator(mode="after")
    def correct_horizon(self):
        if self.target_time - self.cutoff_time != timedelta(minutes=5):
            raise ValueError("Target must be exactly cutoff + 5 minutes")
        return self


class ForecastRow(Contract):
    hex_id: Name
    forecast_demand: NonNegative
    forecast_supply: NonNegative


class Forecast(TestOnly):
    schema_version: Literal["ggso.forecast.v2"]
    identity: Identity
    forecast_run_id: Name
    forecast_model_id: Name
    checkpoint_version: Name
    checkpoint_contract: Literal["duocast_ds_h5_v1"]
    history_steps: Annotated[int, Field(gt=0, strict=True)]
    demand_definition: Literal["confirmed_valid_bookings_per_5min"]
    supply_definition: Literal["online_idle_dispatch_eligible_stock_at_target"]
    parity_status: Literal["TEST_ONLY_MOCK_VERIFIED", "TEST_ONLY_CHECKPOINT_VERIFIED"]
    parity_evidence: Annotated[tuple[Name, ...], Field(min_length=1)]
    features_available_at: AwareDatetime
    generated_at: AwareDatetime
    rows: tuple[ForecastRow, ...]

    @model_validator(mode="after")
    def coverage_and_time(self):
        if tuple(row.hex_id for row in self.rows) != self.identity.required_hex_ids:
            raise ValueError("Forecast must preserve full required node order")
        if self.features_available_at > self.identity.cutoff_time or self.generated_at < self.identity.cutoff_time:
            raise ValueError("Forecast availability/generation time invalid")
        return self
