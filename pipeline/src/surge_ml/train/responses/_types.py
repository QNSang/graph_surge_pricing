from __future__ import annotations
from pathlib import Path
from typing import Annotated
from pydantic import AwareDatetime, Field, model_validator
from surge_ml.contracts.common import Contract, TestOnly, Name, Nodes, Positive, Number, Probability, Count


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


class ResponseFitJob(Contract):
    """Validated offline job; paths are resolved relative to the configuration file."""
    input: Path
    output: Path
    report: Path | None = None
    dataset_id: Name
    node_mapping_version: Name
    required_hex_ids: Nodes
    artifact_version: Name
    split_time: AwareDatetime
    fit_as_of: AwareDatetime
    fit: FitConfig

    @model_validator(mode="after")
    def chronological(self):
        if self.split_time >= self.fit_as_of:
            raise ValueError("split_time must precede fit_as_of")
        return self
