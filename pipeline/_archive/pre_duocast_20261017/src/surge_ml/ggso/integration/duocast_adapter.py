"""MI-01..08: explicit mock-only GeoMobiNet-row adapter, one inference/network.

This does not relabel or approve an existing real checkpoint. Actual source-label
parity is an independent P7/P8 gate; the only accepted proof here is TEST_ONLY.
"""
from __future__ import annotations
from collections.abc import Callable, Iterable, Mapping
from typing import Annotated, Literal
from pydantic import AwareDatetime, Field
from ..contracts import Contract, Forecast, ForecastRow, Identity, Name, Nodes, NonNegative, TestOnly
from ..errors import require


class MockCheckpoint(TestOnly):
    contract_version: Literal["geomobinet_smg_ds_h5_v1"]
    model_id: Name
    checkpoint_version: Name
    dataset_id: Name
    dataset_fingerprint: Name
    feature_version: Name
    geo_version: Name
    node_mapping_version: Name
    required_hex_ids: Nodes
    history_steps: Annotated[int, Field(gt=0, strict=True)]
    demand_definition: Literal["confirmed_valid_bookings_per_5min"]
    supply_definition: Literal["online_idle_dispatch_eligible_stock_at_target"]
    parity_status: Literal["TEST_ONLY_MOCK_VERIFIED"]
    evidence_refs: Annotated[tuple[Name, ...], Field(min_length=1)]
    features_available_at: AwareDatetime


class RawForecastRow(Contract):
    cutoff_time: AwareDatetime
    target_time: AwareDatetime
    hex_id: Name
    pred_demand: NonNegative
    pred_idle_supply: NonNegative
    ds_proxy: NonNegative | None = None


def check_mock_parity(identity: Identity, checkpoint: MockCheckpoint) -> None:
    for field in ("dataset_id", "dataset_fingerprint", "feature_version", "geo_version",
                  "node_mapping_version", "required_hex_ids"):
        require(getattr(identity, field) == getattr(checkpoint, field),
                "SEMANTIC_MISMATCH", f"Mock checkpoint parity mismatch: {field}")
    require(checkpoint.features_available_at <= identity.cutoff_time,
            "FORECAST_INVALID", "Forecast features unavailable at cutoff")


def adapt_rows(rows: Iterable[Mapping], *, identity: Identity, checkpoint: MockCheckpoint,
               forecast_run_id: str, generated_at) -> Forecast:
    identity = Identity.model_validate(identity)
    checkpoint = MockCheckpoint.model_validate(checkpoint)
    check_mock_parity(identity, checkpoint)
    parsed = tuple(RawForecastRow.model_validate(row) for row in rows)
    require(tuple(row.hex_id for row in parsed) == identity.required_hex_ids,
            "FORECAST_INVALID", "Raw forecast rows do not preserve full checkpoint node order")
    require(all(row.cutoff_time == identity.cutoff_time and row.target_time == identity.target_time for row in parsed),
            "FORECAST_INVALID", "Raw forecast mixes cutoff or target timestamps")
    return Forecast(usage="TEST_ONLY", schema_version="ggso.forecast.v1", identity=identity,
                    forecast_run_id=forecast_run_id, forecast_model_id=checkpoint.model_id,
                    checkpoint_version=checkpoint.checkpoint_version,
                    checkpoint_contract=checkpoint.contract_version, history_steps=checkpoint.history_steps,
                    demand_definition=checkpoint.demand_definition, supply_definition=checkpoint.supply_definition,
                    parity_status=checkpoint.parity_status, parity_evidence=checkpoint.evidence_refs,
                    features_available_at=checkpoint.features_available_at, generated_at=generated_at,
                    rows=tuple(ForecastRow(hex_id=row.hex_id, forecast_demand=row.pred_demand,
                                          forecast_supply=row.pred_idle_supply) for row in parsed))


class DuoCastMockAdapter:
    def __init__(self, infer: Callable[[Identity], Iterable[Mapping]], *, checkpoint: MockCheckpoint,
                 forecast_run_id: str, generated_at):
        self._infer = infer
        self.checkpoint = MockCheckpoint.model_validate(checkpoint)
        self.forecast_run_id = forecast_run_id
        self.generated_at = generated_at

    def __call__(self, identity: Identity) -> Forecast:
        identity = Identity.model_validate(identity)
        check_mock_parity(identity, self.checkpoint)
        rows = self._infer(identity)  # Exactly one batched invocation, outside all candidate loops.
        return adapt_rows(rows, identity=identity, checkpoint=self.checkpoint,
                          forecast_run_id=self.forecast_run_id, generated_at=self.generated_at)
