"""Decimal surge rules, recommendation consistency (Layer B) and eligibility (spec §5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.core.config import Policy, SurgeLimits
from app.core.errors import AppError
from app.domain.enums import DecisionAction, Eligibility, RecommendationAction, ValidationStatus


def parse_decimal(value) -> Decimal | None:
    """Parse a decimal string/number; returns None for null. Raises ValueError for non-finite or garbage."""
    if value is None:
        return None
    if isinstance(value, float):
        value = repr(value)
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"not a decimal: {value!r}") from exc
    if not d.is_finite():
        raise ValueError(f"non-finite decimal: {value!r}")
    return d


def quantize(value: Decimal, precision: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)


def fmt(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def check_surge_value(value: Decimal, base: Decimal, limits: SurgeLimits, context: dict) -> None:
    """Strict check; never clamps. Raises AppError with the spec error code."""
    exponent = value.normalize().as_tuple().exponent
    if isinstance(exponent, int) and -exponent > limits.precision:
        raise AppError("INVALID_SURGE_PRECISION", f"Surge must have at most {limits.precision} decimals.", context)
    if (value - limits.min) % limits.step != 0:
        raise AppError("INVALID_SURGE_STEP", f"Surge must be on step {limits.step}.", context)
    if value < limits.min or value > limits.max:
        raise AppError(
            "SURGE_LIMIT_EXCEEDED",
            f"Surge must be within [{limits.min}, {limits.max}].",
            {**context, "min": str(limits.min), "max": str(limits.max)},
        )
    if abs(value - base) > limits.max_deviation:
        raise AppError(
            "SURGE_LIMIT_EXCEEDED",
            f"Surge deviates more than {limits.max_deviation} from base.",
            {**context, "surge_base": str(base), "max_deviation": str(limits.max_deviation)},
        )


def consistency_errors(action: str, base: Decimal | None, delta: Decimal | None, proposed: Decimal | None) -> list[str]:
    """Layer B action/surge consistency. Returns error codes (empty == consistent)."""
    errors: list[str] = []
    if base is None:
        return ["SURGE_BASE_MISSING"]
    if action == RecommendationAction.REVIEW:
        return errors  # REVIEW carries no approvable price; nothing to compare.
    if proposed is None:
        return ["SURGE_PROPOSED_MISSING"]
    if action == RecommendationAction.INCREASE and not proposed > base:
        errors.append("ACTION_SURGE_MISMATCH")
    elif action == RecommendationAction.DECREASE and not proposed < base:
        errors.append("ACTION_SURGE_MISMATCH")
    elif action == RecommendationAction.HOLD and proposed != base:
        errors.append("ACTION_SURGE_MISMATCH")
    if delta is not None and delta != proposed - base:
        errors.append("DELTA_MISMATCH")
    return errors


@dataclass
class EligibilityResult:
    state: Eligibility
    blocked_reasons: list[str] = field(default_factory=list)
    capabilities: dict[str, bool] = field(default_factory=dict)


def evaluate_eligibility(
    *,
    action: str,
    validation_status: str,
    surge_base: Decimal | None,
    surge_proposed: Decimal | None,
    rec_policy_version: str,
    superseded: bool,
    policy: Policy,
) -> EligibilityResult:
    """Server-side eligibility; independent of action. No wall-clock TTL in DEMO_REPLAY (spec §5.5)."""
    reasons: list[str] = []
    state = Eligibility.ELIGIBLE
    if validation_status != ValidationStatus.VALID:
        state = Eligibility.BLOCKED
        reasons.append("VALIDATION_FAILED")
    elif superseded:
        state = Eligibility.SUPERSEDED
        reasons.append("PROPOSAL_SUPERSEDED")
    elif rec_policy_version != policy.policy_version:
        state = Eligibility.BLOCKED
        reasons.append("POLICY_VERSION_CONFLICT")
    elif action in (RecommendationAction.INCREASE, RecommendationAction.DECREASE) and surge_proposed is not None:
        try:
            check_surge_value(surge_proposed, surge_base, policy.limits, {})
        except AppError as err:
            state = Eligibility.BLOCKED
            reasons.append(err.code)

    eligible = state == Eligibility.ELIGIBLE
    is_review = action == RecommendationAction.REVIEW
    if eligible and is_review:
        reasons.append("REVIEW_REQUIRED")
    if eligible and action == RecommendationAction.HOLD:
        reasons.append("HOLD_NO_ACTION")
    movable = action in (RecommendationAction.INCREASE, RecommendationAction.DECREASE)
    capabilities = {
        "accept": eligible and movable,
        "keep_bidding": eligible and not is_review,
        "override": eligible
        and (movable or (action == RecommendationAction.HOLD and policy.allow_hold_override)),
    }
    return EligibilityResult(state=state, blocked_reasons=reasons, capabilities=capabilities)


CAPABILITY_FOR_ACTION = {
    DecisionAction.ACCEPT_PROPOSAL: "accept",
    DecisionAction.KEEP_BIDDING: "keep_bidding",
    DecisionAction.OVERRIDE_PROPOSAL: "override",
}

ELIGIBILITY_ERROR = {
    Eligibility.BLOCKED: "PROPOSAL_BLOCKED",
    Eligibility.EXPIRED: "PROPOSAL_EXPIRED",
    Eligibility.SUPERSEDED: "PROPOSAL_SUPERSEDED",
    Eligibility.UNKNOWN: "PROPOSAL_BLOCKED",
}
