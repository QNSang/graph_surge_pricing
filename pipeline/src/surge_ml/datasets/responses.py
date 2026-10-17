from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
import numpy as np
from pydantic import AwareDatetime, model_validator
from surge_ml.contracts.common import Count, Name, NonNegative, Price, TestOnly, Transform, Vector
from surge_ml.errors import require

class Observation(TestOnly):
    hex_id: Name
    decision_time: AwareDatetime
    target_time: AwareDatetime
    feature_available_at: AwareDatetime
    outcome_matured_at: AwareDatetime
    cohort_id: Name
    cohort_profile: Literal["confirmed_bookings_and_matured_completions.h5.test.v1"]
    capacity_definition: Literal["rides_per_horizon.h5.test.v1"]
    applied_surge: Price
    booking_demand: Count
    completed_bookings: Count
    effective_capacity: NonNegative
    demand_context: Vector
    fulfillment_context: Vector

    @model_validator(mode="after")
    def semantics(self):
        if self.completed_bookings > self.booking_demand:
            raise ValueError("C must be completions of the same D cohort, 0 <= C <= D")
        if self.target_time - self.decision_time != timedelta(minutes=5):
            raise ValueError("Cohort horizon must be five minutes")
        if self.feature_available_at > self.decision_time or self.outcome_matured_at < self.target_time:
            raise ValueError("Future feature or immature cohort")
        return self


@dataclass(frozen=True)
class Arrays:
    demand: np.ndarray
    completed: np.ndarray
    surge: np.ndarray
    capacity: np.ndarray
    demand_context: np.ndarray
    fulfillment_context: np.ndarray

    def take(self, indices: np.ndarray) -> "Arrays":
        return Arrays(*(getattr(self, key)[indices] for key in self.__dataclass_fields__))


def fit_transform(vectors: list[Vector]) -> Transform:
    require(bool(vectors), "RESPONSE_INVALID", "No training context")
    first = vectors[0]
    require(all(v.names == first.names and v.schema_version == first.schema_version for v in vectors),
            "RESPONSE_INVALID", "Inconsistent ordered context schema")
    raw = np.array([v.values for v in vectors], dtype=float)
    if len(first.names):
        mean, scale = raw.mean(axis=0), raw.std(axis=0)
        # Constant training covariates remain zero after transformation; no test information is used.
        scale[scale == 0] = 1.0
        low, high = raw.min(axis=0), raw.max(axis=0)
    else:
        mean = scale = low = high = np.array([], dtype=float)
    return Transform(version="standardize_train.v1", names=first.names, schema_version=first.schema_version,
                     mean=tuple(mean.tolist()), scale=tuple(scale.tolist()),
                     support_min=tuple(low.tolist()), support_max=tuple(high.tolist()))


def to_arrays(rows: list[Observation], demand_transform: Transform, fulfillment_transform: Transform) -> Arrays:
    return Arrays(np.array([r.booking_demand for r in rows], dtype=float),
                  np.array([r.completed_bookings for r in rows], dtype=float),
                  np.array([float(r.applied_surge) for r in rows]),
                  np.array([r.effective_capacity for r in rows]),
                  np.array([demand_transform.apply(r.demand_context) for r in rows]),
                  np.array([fulfillment_transform.apply(r.fulfillment_context) for r in rows]))


def chronological_split(rows: list[Observation], split_time: datetime, fit_as_of: datetime):
    require(split_time.tzinfo is not None and fit_as_of.tzinfo is not None and split_time < fit_as_of,
            "RESPONSE_INVALID", "Explicit aware chronological split and fit cutoff required")
    validated = [Observation.model_validate(r) for r in rows]
    require(len({r.hex_id for r in validated}) == 1, "RESPONSE_INVALID", "Fit exactly one cell independently")
    require(len({(r.hex_id, r.decision_time) for r in validated}) == len(validated),
            "RESPONSE_INVALID", "Duplicate response decision row")
    require(len({r.cohort_id for r in validated}) == len(validated), "RESPONSE_INVALID", "Duplicate cohort")
    require(all(r.outcome_matured_at <= fit_as_of for r in validated),
            "RESPONSE_INVALID", "Outcome not available at artifact fit cutoff")
    ordered = sorted(validated, key=lambda row: row.decision_time)
    train = [r for r in ordered if r.decision_time < split_time]
    validation = [r for r in ordered if r.decision_time >= split_time]
    require(bool(train) and bool(validation), "RESPONSE_INVALID", "Empty train/validation partition")
    require(all(r.outcome_matured_at <= split_time for r in train),
            "RESPONSE_INVALID", "Training labels cross validation boundary; supply an explicit embargo")
    td = fit_transform([r.demand_context for r in train])
    tf = fit_transform([r.fulfillment_context for r in train])
    return train, validation, to_arrays(train, td, tf), to_arrays(validation, td, tf), td, tf
