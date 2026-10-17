"""Immutable, versioned P1-P6 contracts. Unverified real profiles fail closed."""
from __future__ import annotations

import math
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from pydantic import AfterValidator, AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected numeric JSON value, not string/bool/null")
    if not math.isfinite(value):
        raise ValueError("Nonfinite number")
    return value


def _decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, Decimal)):
        raise ValueError("Prices/actions require decimal strings or Decimal")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal") from exc
    if not result.is_finite():
        raise ValueError("Nonfinite decimal")
    return result


def _unique(values):
    if len(set(values)) != len(values):
        raise ValueError("Duplicate values")
    return values


Number = Annotated[float, BeforeValidator(_number)]
NonNegative = Annotated[Number, Field(ge=0)]
Positive = Annotated[Number, Field(gt=0)]
Probability = Annotated[Number, Field(ge=0, le=1)]
Price = Annotated[Decimal, BeforeValidator(_decimal), Field(gt=0)]
Adjustment = Annotated[Decimal, BeforeValidator(_decimal)]
Name = Annotated[str, Field(min_length=1, strict=True)]
Names = Annotated[tuple[Name, ...], AfterValidator(_unique)]
Nodes = Annotated[Names, Field(min_length=1)]
Count = Annotated[int, Field(ge=0, strict=True)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False,
                              validate_default=True, revalidate_instances="always")


class TestOnly(Contract):
    usage: Literal["TEST_ONLY"]
    production_eligible: Literal[False] = False


class Identity(TestOnly):
    snapshot_id: Name
    decision_id: Name
    dataset_id: Name
    dataset_fingerprint: Name
    node_mapping_version: Name
    feature_version: Name
    geo_version: Name
    reference_policy_version: Name
    semantic_profile_id: Literal["ggso.confirmed-bookings.eligible-idle.h5.test.v1"]
    cutoff_time: AwareDatetime
    target_time: AwareDatetime
    required_hex_ids: Nodes
    horizon_minutes: Literal[5]

    @model_validator(mode="after")
    def correct_horizon(self):
        if self.target_time - self.cutoff_time != timedelta(minutes=5):
            raise ValueError("Target must be exactly cutoff + 5 minutes")
        return self


class Vector(Contract):
    names: Names
    values: tuple[Number, ...]
    schema_version: Name

    @model_validator(mode="after")
    def dimensions(self):
        if len(self.names) != len(self.values):
            raise ValueError("Context names/values dimension mismatch")
        return self


class Transform(Contract):
    version: Literal["standardize_train.v1"]
    names: Names
    schema_version: Name
    mean: tuple[Number, ...]
    scale: tuple[Positive, ...]
    support_min: tuple[Number, ...]
    support_max: tuple[Number, ...]

    @model_validator(mode="after")
    def dimensions(self):
        if any(len(x) != len(self.names) for x in
               (self.mean, self.scale, self.support_min, self.support_max)):
            raise ValueError("Preprocessing dimensions differ")
        if any(lo > hi for lo, hi in zip(self.support_min, self.support_max)):
            raise ValueError("Invalid context support range")
        return self

    def apply(self, vector: Vector, *, check_support: bool = False) -> tuple[float, ...]:
        if vector.names != self.names or vector.schema_version != self.schema_version:
            raise ValueError("Context schema/ordered features differ from fitted model")
        if check_support and any(not lo <= x <= hi for x, lo, hi in
                                 zip(vector.values, self.support_min, self.support_max)):
            raise ValueError("Context outside training support")
        return tuple((x - m) / s for x, m, s in zip(vector.values, self.mean, self.scale))


class ForecastRow(Contract):
    hex_id: Name
    forecast_demand: NonNegative
    forecast_supply: NonNegative


class Forecast(TestOnly):
    schema_version: Literal["ggso.forecast.v1"]
    identity: Identity
    forecast_run_id: Name
    forecast_model_id: Name
    checkpoint_version: Name
    checkpoint_contract: Literal["geomobinet_smg_ds_h5_v1"]
    history_steps: Annotated[int, Field(gt=0, strict=True)]
    demand_definition: Literal["confirmed_valid_bookings_per_5min"]
    supply_definition: Literal["online_idle_dispatch_eligible_stock_at_target"]
    parity_status: Literal["TEST_ONLY_MOCK_VERIFIED"]
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


class CapacitySource(Contract):
    method: Literal["DIRECT", "GGSO_IDLE_APPROXIMATION"]
    source_version: Name
    available_at: AwareDatetime
    horizon_minutes: Literal[5]
    units: Literal["rides_per_horizon"]
    direct_capacity: NonNegative | None
    rides_per_driver_hour: NonNegative | None
    eta: NonNegative | None
    eta_unit: Literal["minutes", "seconds"] | None
    calibration_version: Name

    @model_validator(mode="after")
    def exactly_one_method(self):
        if self.method == "DIRECT":
            if self.direct_capacity is None or any(x is not None for x in
                    (self.rides_per_driver_hour, self.eta, self.eta_unit)):
                raise ValueError("Direct K requires K only, not approximation inputs")
        elif self.direct_capacity is not None or any(x is None for x in
                (self.rides_per_driver_hour, self.eta, self.eta_unit)):
            raise ValueError("Approximation requires explicit r, ETA and ETA unit")
        return self


class OperationalRow(Contract):
    hex_id: Name
    current_surge: Price
    reference_fare: NonNegative
    fare_definition_version: Name
    available_at: AwareDatetime
    price_state: Literal["SIMULATED_EFFECTIVE"]
    price_source_version: Name
    quote_opportunities: NonNegative
    quote_source_kind: Literal["FORECAST_AS_OF", "FROZEN_ELIGIBLE"]
    quote_source_version: Name
    quote_cohort_profile: Literal["confirmed_bookings_over_compatible_quotes.h5.test.v1"]
    quote_window_start: AwareDatetime
    quote_window_end: AwareDatetime
    quote_available_at: AwareDatetime
    capacity: CapacitySource
    demand_context: Vector
    fulfillment_context: Vector


class Edge(Contract):
    source: Name
    target: Name
    weight: NonNegative


class OperationalSnapshot(TestOnly):
    schema_version: Literal["ggso.operational.v1"]
    identity: Identity
    currency: Name
    rows: tuple[OperationalRow, ...]
    pricing_edges: tuple[Edge, ...]
    pricing_graph_version: Name
    pricing_graph_available_at: AwareDatetime

    @model_validator(mode="after")
    def coherent_snapshot(self):
        identity = self.identity
        if tuple(row.hex_id for row in self.rows) != identity.required_hex_ids:
            raise ValueError("Operational rows must match exact full node order")
        for row in self.rows:
            if any(t > identity.cutoff_time for t in
                   (row.available_at, row.quote_available_at, row.capacity.available_at)):
                raise ValueError("Operational source unavailable at cutoff")
            if row.price_source_version != identity.reference_policy_version:
                raise ValueError("Effective price version mismatch")
            if (row.quote_window_start, row.quote_window_end) != (identity.cutoff_time, identity.target_time):
                raise ValueError("Quote and booking horizons differ")
        seen = set()
        for edge in self.pricing_edges:
            key = tuple(sorted((edge.source, edge.target)))
            if edge.source == edge.target or not set(key).issubset(identity.required_hex_ids) or key in seen:
                raise ValueError("Unknown/self/duplicate undirected pricing edge")
            seen.add(key)
        if self.pricing_graph_available_at > identity.cutoff_time:
            raise ValueError("Pricing graph is from the future")
        return self


class Scenario(Contract):
    scenario_id: Name
    beta: Annotated[Number, Field(ge=0, le=4)]
    gamma: Probability
    weight: Positive


class Support(Contract):
    train_rows: Count
    validation_rows: Count
    positive_trial_rows: Count
    unique_surge_values: Count
    surge_min: Price
    surge_max: Price
    train_start: AwareDatetime
    train_end: AwareDatetime
    validation_start: AwareDatetime
    validation_end: AwareDatetime

    @model_validator(mode="after")
    def ordered(self):
        if not self.train_start <= self.train_end < self.validation_start <= self.validation_end:
            raise ValueError("Response windows overlap or are not chronological")
        if self.surge_min >= self.surge_max:
            raise ValueError("Response needs observed surge variation")
        return self


class Calibration(Contract):
    status: Literal["SYNTHETIC_PASS", "INELIGIBLE"]
    rule_version: Name
    demand_mean_nll: Number
    fulfillment_mean_nll: Number
    fulfillment_calibration_error: NonNegative
    evidence_refs: Annotated[tuple[Name, ...], Field(min_length=1)]
    rejection_reasons: tuple[Name, ...]

    @model_validator(mode="after")
    def consistent(self):
        if (self.status == "SYNTHETIC_PASS") != (not self.rejection_reasons):
            raise ValueError("Eligibility status and reasons disagree")
        return self


class ResponseCell(Contract):
    hex_id: Name
    demand_intercept: Number
    demand_coefficients: tuple[Number, ...]
    beta: Annotated[Number, Field(ge=0, le=4)]
    nb_dispersion: Positive
    fulfillment_intercept: Number
    fulfillment_coefficients: tuple[Number, ...]
    gamma: Probability
    demand_transform: Transform
    fulfillment_transform: Transform
    fit_status: Literal["CONVERGED"]
    support: Support
    calibration: Calibration
    scenarios: Annotated[tuple[Scenario, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def dimensions_and_scenarios(self):
        if len(self.demand_coefficients) != len(self.demand_transform.names):
            raise ValueError("Demand coefficient dimension mismatch")
        if len(self.fulfillment_coefficients) != len(self.fulfillment_transform.names):
            raise ValueError("Fulfillment coefficient dimension mismatch")
        if len({x.scenario_id for x in self.scenarios}) != len(self.scenarios):
            raise ValueError("Duplicate scenario IDs")
        expected = 1.0 / len(self.scenarios)
        if any(not math.isclose(x.weight, expected, rel_tol=0, abs_tol=1e-12) for x in self.scenarios):
            raise ValueError("linear_equal_weight requires complete uniformly weighted scenarios")
        return self


class ResponseArtifact(TestOnly):
    schema_version: Literal["ggso.response.v1"]
    artifact_version: Name
    semantic_profile_id: Literal["ggso.confirmed-bookings.eligible-idle.h5.test.v1"]
    node_mapping_version: Name
    required_hex_ids: Nodes
    dataset_id: Name
    data_fingerprint: Name
    available_at: AwareDatetime
    nb_parameterization: Literal["NB2_mean_size_variance_mu_plus_mu_squared_over_k"]
    estimation_method: Literal["scipy_lbfgsb_mle.test.v1"]
    context_representation: Literal["tabular_v1"]
    training_objective_demand: Literal["negative_binomial_nll"]
    training_objective_fulfillment: Literal["binomial_nll"]
    epsilon: Positive
    scenario_method: Literal["paired_moving_block_bootstrap.test.v1", "declared_synthetic_parameters.test.v1"]
    scenario_seed: Count
    scenario_block_size: Annotated[int, Field(gt=0, strict=True)]
    scenario_count: Annotated[int, Field(gt=0, strict=True)]
    quantile_method: Literal["linear_equal_weight"]
    quantile: Literal[0.05]
    cells: tuple[ResponseCell, ...]

    @model_validator(mode="after")
    def full_artifact(self):
        if tuple(c.hex_id for c in self.cells) != self.required_hex_ids:
            raise ValueError("Response must cover exact full node order")
        for cell in self.cells:
            if len(cell.scenarios) != self.scenario_count:
                raise ValueError("Scenario count mismatch; cannot drop failed fits")
            if cell.support.validation_end > self.available_at:
                raise ValueError("Artifact precedes validation data")
        return self


class Outcome(Contract):
    expected_demand: NonNegative
    fulfillment_rate: Probability
    expected_completed: NonNegative
    expected_gmv: NonNegative


class Candidate(Contract):
    candidate_id: Name
    decision_id: Name
    snapshot_id: Name
    hex_id: Name
    action: Adjustment
    proposed_surge: Price
    outcome: Outcome
    incremental_gmv: Number
    conservative_utility: Number
    scenario_ids: Names
    scenario_increments: tuple[Number, ...]

    @model_validator(mode="after")
    def scenario_dimensions(self):
        if len(self.scenario_ids) != len(self.scenario_increments) or not self.scenario_ids:
            raise ValueError("Missing/unpaired scenario increments")
        return self


class RejectedCandidate(Contract):
    hex_id: Name
    action: Adjustment
    proposed_surge: Adjustment
    reasons: Annotated[tuple[Name, ...], Field(min_length=1)]


class CandidateTable(TestOnly):
    schema_version: Literal["ggso.candidates.v1"]
    identity: Identity
    forecast_run_id: Name
    response_version: Name
    policy_config_version: Name
    currency: Name
    candidates: tuple[Candidate, ...]
    rejected: tuple[RejectedCandidate, ...]

    @model_validator(mode="after")
    def identity_and_coverage(self):
        if len({c.candidate_id for c in self.candidates}) != len(self.candidates):
            raise ValueError("Duplicate candidate ID")
        pairs = [(c.hex_id, c.action) for c in self.candidates]
        if len(set(pairs)) != len(pairs):
            raise ValueError("Duplicate cell/action")
        if {c.hex_id for c in self.candidates} != set(self.identity.required_hex_ids):
            raise ValueError("Missing/extra candidate cell")
        if any(c.decision_id != self.identity.decision_id or c.snapshot_id != self.identity.snapshot_id
               for c in self.candidates):
            raise ValueError("Mixed candidate snapshots")
        return self


class SolverInfo(Contract):
    engine: Literal["scipy.optimize.milp/HiGHS"]
    scipy_version: Name
    raw_status: int | None
    message: str
    accepted_status: Literal["OPTIMAL", "FEASIBLE_LIMIT", "FEASIBLE_GAP", "REJECTED"]
    runtime_seconds: NonNegative
    raw_objective: Number | None
    dual_bound: Number | None
    mip_gap: NonNegative | None


class Metrics(Contract):
    booking_rate: NonNegative
    expected_demand: NonNegative
    quote_opportunities: Positive
    expected_gmv: NonNegative
    reference_gmv: NonNegative
    nominal_incremental_gmv: Number
    conservative_utility: Number
    temporal_penalty: NonNegative
    spatial_penalty: NonNegative
    objective: Number


class Recommendation(Contract):
    candidate_id: Name
    hex_id: Name
    action: Literal["INCREASE", "DECREASE", "HOLD"]
    surge_base: Price
    surge_delta: Adjustment
    surge_proposed: Price


class ConstraintChecks(Contract):
    validator_version: Literal["ggso.independent.v1"]
    coverage: Literal[True]
    identity: Literal[True]
    grid_and_bounds: Literal[True]
    candidate_recomputed: Literal[True]
    booking_rate: Literal[True]
    nominal_no_loss: Literal[True]
    integrality: Literal[True]


class DecisionResult(TestOnly):
    schema_version: Literal["ggso.decision.v1"]
    result_status: Literal["VALID", "INVALID"]
    identity: Identity | None
    generated_at: AwareDatetime
    forecast_version: str | None
    response_version: str | None
    policy_config_version: str | None
    currency: str | None
    error_code: str | None
    diagnostics: tuple[str, ...]
    trace: tuple[str, ...]
    selected_candidates: tuple[Candidate, ...]
    recommendations: tuple[Recommendation, ...]
    optimized_policy: dict[str, str] | None
    estimated_metrics: Metrics | None
    constraint_checks: ConstraintChecks | None
    solver: SolverInfo | None
    publication: Literal["NOT_REQUESTED"] = "NOT_REQUESTED"
    production_effective: Literal[False] = False
    applied_vector_certified: Literal[False] = False

    @model_validator(mode="after")
    def never_emit_partial_or_fallback(self):
        if self.result_status == "INVALID":
            if (not self.error_code or self.recommendations or self.selected_candidates
                    or self.optimized_policy is not None or self.estimated_metrics is not None
                    or self.constraint_checks is not None):
                raise ValueError("INVALID cannot contain policy/recommendations")
            return self
        if (self.error_code is not None or self.identity is None or self.optimized_policy is None
                or self.estimated_metrics is None or self.constraint_checks is None or self.solver is None
                or self.solver.accepted_status == "REJECTED"):
            raise ValueError("VALID needs full policy and independent/solver evidence")
        nodes = self.identity.required_hex_ids
        if (tuple(r.hex_id for r in self.recommendations) != nodes
                or tuple(c.hex_id for c in self.selected_candidates) != nodes
                or set(self.optimized_policy) != set(nodes)):
            raise ValueError("VALID requires full coverage")
        for rec, candidate in zip(self.recommendations, self.selected_candidates):
            action = "INCREASE" if candidate.action > 0 else "DECREASE" if candidate.action < 0 else "HOLD"
            if (rec.candidate_id != candidate.candidate_id or rec.action != action
                    or rec.surge_delta != candidate.action or rec.surge_proposed != candidate.proposed_surge
                    or rec.surge_base + rec.surge_delta != rec.surge_proposed
                    or Decimal(self.optimized_policy[rec.hex_id]) != rec.surge_proposed):
                raise ValueError("Recommendation and selected policy disagree")
        return self
