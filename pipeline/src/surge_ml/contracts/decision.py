from __future__ import annotations
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import AwareDatetime, Field, model_validator
from .common import (Contract, TestOnly, Name, Names, Price, Adjustment, Number,
                     Positive, Probability, NonNegative, Vector)
from .forecast import Identity

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
    schema_version: Literal["ggso.operational.v2"]
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
    schema_version: Literal["ggso.candidates.v2"]
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
    schema_version: Literal["ggso.decision.v2"]
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
