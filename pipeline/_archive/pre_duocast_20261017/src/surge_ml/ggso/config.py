"""Explicit TEST_ONLY numerical configuration, never production defaults."""
from __future__ import annotations
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .contracts import Adjustment, Count, Name, NonNegative, Number, Positive, Price, Probability, TestOnly


class PolicyConfig(TestOnly):
    schema_version: Literal["ggso.policy.test.v1"]
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


class FitConfig(TestOnly):
    version: Name
    epsilon: Positive
    max_iterations: Annotated[int, Field(gt=0, strict=True)]
    log_dispersion_min: Number
    log_dispersion_max: Number
    min_train_rows: Annotated[int, Field(gt=1, strict=True)]
    min_validation_rows: Annotated[int, Field(gt=0, strict=True)]
    min_positive_trial_rows: Annotated[int, Field(gt=0, strict=True)]
    min_unique_surge: Annotated[int, Field(ge=2, strict=True)]
    max_demand_mean_nll: Positive
    max_fulfillment_mean_nll: Positive
    max_fulfillment_calibration_error: Probability
    bootstrap_replicates: Annotated[int, Field(gt=0, strict=True)]
    bootstrap_block_size: Annotated[int, Field(gt=0, strict=True)]
    seed: Count

    @model_validator(mode="after")
    def numeric_bounds(self):
        if not -20 <= self.log_dispersion_min < self.log_dispersion_max <= 20:
            raise ValueError("Declare a finite usable TEST_ONLY log-size fitting interval")
        return self
