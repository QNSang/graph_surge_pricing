from __future__ import annotations

from enum import StrEnum


class RecommendationAction(StrEnum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    HOLD = "HOLD"
    REVIEW = "REVIEW"


class Eligibility(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    UNKNOWN = "UNKNOWN"


class ValidationStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"


class DecisionAction(StrEnum):
    ACCEPT_PROPOSAL = "ACCEPT_PROPOSAL"
    KEEP_BIDDING = "KEEP_BIDDING"
    OVERRIDE_PROPOSAL = "OVERRIDE_PROPOSAL"


class DecisionStatus(StrEnum):
    RECORDED = "RECORDED"
    KEPT_BIDDING = "KEPT_BIDDING"


FINAL_DECISION_STATUSES = (DecisionStatus.RECORDED.value, DecisionStatus.KEPT_BIDDING.value)


class RecommendationSetStatus(StrEnum):
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"


class BatchStatus(StrEnum):
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"


class BatchItemStatus(StrEnum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class SelectionMode(StrEnum):
    ALL_ELIGIBLE = "ALL_ELIGIBLE"
    SELECTED = "SELECTED"


class SeriesKind(StrEnum):
    BASE_BIDDING = "BASE_BIDDING"
    DEMAND = "DEMAND"
    EFFECTIVE_SUPPLY = "EFFECTIVE_SUPPLY"
    OBSERVED_DS = "OBSERVED_DS"
    FORECAST_DS = "FORECAST_DS"


class DataKind(StrEnum):
    SYNTHETIC = "SYNTHETIC"
    HISTORICAL = "HISTORICAL"
    LIVE = "LIVE"
