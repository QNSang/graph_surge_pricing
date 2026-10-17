from __future__ import annotations
import math
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import Field, model_validator
from surge_ml.contracts.common import (Adjustment, Count, Name, NonNegative, Number,
                                      Positive, Price, Probability, TestOnly, Contract)
from surge_ml.contracts.forecast import Forecast
from surge_ml.contracts.response import ResponseArtifact
from surge_ml.contracts.decision import OperationalSnapshot
from surge_ml.errors import require

class PolicyConfig(TestOnly):
    schema_version: Literal["ggso.policy.test.v2"]
    version: Name
    currency: Name
    surge_min: Price
    surge_max: Price
    delta_max: Adjustment
    br_min: Probability
    br_max: Probability
    lambda_temporal: NonNegative
    lambda_spatial: NonNegative
    epsilon: Positive
    quantile: Literal[0.05]
    quantile_method: Literal["linear_equal_weight"]
    solver_time_limit_seconds: Positive
    solver_mip_rel_gap: NonNegative
    integrality_tolerance: Annotated[Positive, Field(lt=0.01)]
    feasibility_tolerance: Annotated[Positive, Field(lt=0.01)]
    money_tolerance: NonNegative
    monetary_scale: Positive

    @model_validator(mode="after")
    def coherent(self):
        if self.surge_min >= self.surge_max or not Decimal(0) <= self.delta_max <= Decimal("0.3"):
            raise ValueError("Invalid surge/adjustment bounds")
        if self.br_min > self.br_max:
            raise ValueError("Contradictory booking rate bounds")
        return self


class PreparedNetwork(Contract):
    forecast: Forecast
    operational: OperationalSnapshot
    response: ResponseArtifact
    policy: PolicyConfig

    @property
    def identity(self):
        return self.forecast.identity


def prepare_network(forecast: Forecast, operational: OperationalSnapshot,
                    response: ResponseArtifact, policy: PolicyConfig) -> PreparedNetwork:
    forecast = Forecast.model_validate(forecast)
    operational = OperationalSnapshot.model_validate(operational)
    response = ResponseArtifact.model_validate(response)
    policy = PolicyConfig.model_validate(policy)
    identity = forecast.identity
    require(identity == operational.identity, "SEMANTIC_MISMATCH", "Frozen snapshot identities differ")
    require(response.required_hex_ids == identity.required_hex_ids
            and response.node_mapping_version == identity.node_mapping_version
            and response.semantic_profile_id == identity.semantic_profile_id,
            "RESPONSE_INVALID", "Response network/semantic identity mismatch")
    require(response.available_at <= identity.cutoff_time, "RESPONSE_INVALID", "Response artifact from the future")
    require(response.epsilon == policy.epsilon and response.quantile_method == policy.quantile_method
            and response.quantile == policy.quantile, "RESPONSE_INVALID", "Numerical convention mismatch")
    require(operational.currency == policy.currency, "INPUT_INVALID", "Mixed monetary units")
    require(math.isfinite(sum(row.quote_opportunities for row in operational.rows))
            and sum(row.quote_opportunities for row in operational.rows) > 0,
            "INPUT_INVALID", "Q_total=0 is undefined, not BR=0")
    for forecast_row, row, cell in zip(forecast.rows, operational.rows, response.cells):
        require(cell.calibration.status == "SYNTHETIC_PASS", "RESPONSE_INVALID",
                f"Response ineligible for {cell.hex_id}: {cell.calibration.rejection_reasons}")
        require(forecast_row.forecast_demand <= row.quote_opportunities, "INPUT_INVALID",
                f"Baseline D exceeds compatible Q for {row.hex_id}; no clipping rule is approved")
        require(cell.support.surge_min <= row.current_surge <= cell.support.surge_max,
                "RESPONSE_INVALID", f"Reference surge is outside trained response support for {row.hex_id}")
        # Baseline may be outside policy bounds, but not outside response support.
        # Both contexts must remain within the explicit training support rectangle.
        cell.demand_transform.apply(row.demand_context, check_support=True)
        cell.fulfillment_transform.apply(row.fulfillment_context, check_support=True)
    return PreparedNetwork(forecast=forecast, operational=operational, response=response, policy=policy)
