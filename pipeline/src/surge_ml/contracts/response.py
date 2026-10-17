from __future__ import annotations
import math
from typing import Annotated, Literal
from pydantic import AwareDatetime, Field, model_validator
from .common import (Contract, TestOnly, Name, Nodes, Count, Price, Number, Positive,
                     Probability, NonNegative, Transform)

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
    schema_version: Literal["ggso.response.v2"]
    artifact_version: Name
    semantic_profile_id: Literal["ggso.confirmed-bookings.eligible-idle.h5.test.v2"]
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
