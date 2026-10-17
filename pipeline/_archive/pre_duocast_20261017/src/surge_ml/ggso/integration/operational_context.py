"""Freeze and validate full-network operational/forecast/response identities."""
from __future__ import annotations
import math
from ..config import PolicyConfig
from ..contracts import Contract, Forecast, OperationalSnapshot, ResponseArtifact
from ..errors import require


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
        # Both contexts must remain within the explicit training support rectangle.
        cell.demand_transform.apply(row.demand_context, check_support=True)
        cell.fulfillment_transform.apply(row.fulfillment_context, check_support=True)
    return PreparedNetwork(forecast=forecast, operational=operational, response=response, policy=policy)
