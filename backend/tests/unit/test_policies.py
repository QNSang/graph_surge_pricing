from dataclasses import replace
from decimal import Decimal

import pytest

from app.core.config import get_policy
from app.core.errors import AppError
from app.domain.enums import Eligibility
from app.domain.policies import (
    check_surge_value,
    consistency_errors,
    evaluate_eligibility,
    parse_decimal,
    quantize,
)

D = Decimal


@pytest.fixture
def policy():
    return get_policy()


def test_parse_decimal_rejects_non_finite():
    assert parse_decimal("1.25") == D("1.25")
    assert parse_decimal(None) is None
    for bad in ("NaN", "Infinity", "abc", float("nan")):
        with pytest.raises(ValueError):
            parse_decimal(bad)


def test_quantize_half_up():
    assert quantize(D("1.235"), 2) == D("1.24")
    assert quantize(D("1.234"), 2) == D("1.23")


@pytest.mark.parametrize(
    "value,code",
    [
        ("1.234", "INVALID_SURGE_PRECISION"),
        ("3.50", "SURGE_LIMIT_EXCEEDED"),
        ("0.90", "SURGE_LIMIT_EXCEEDED"),
        ("1.70", "SURGE_LIMIT_EXCEEDED"),  # deviation 0.50 > 0.40 from base 1.20
    ],
)
def test_check_surge_value_never_clamps(policy, value, code):
    with pytest.raises(AppError) as err:
        check_surge_value(D(value), D("1.20"), policy.limits, {})
    assert err.value.code == code


def test_check_surge_value_step(policy):
    limits = replace(policy.limits, step=D("0.05"))
    with pytest.raises(AppError) as err:
        check_surge_value(D("1.23"), D("1.20"), limits, {})
    assert err.value.code == "INVALID_SURGE_STEP"
    check_surge_value(D("1.25"), D("1.20"), limits, {})


def test_check_surge_value_ok_at_bounds(policy):
    check_surge_value(D("1.60"), D("1.20"), policy.limits, {})
    check_surge_value(D("1.00"), D("1.20"), policy.limits, {})


@pytest.mark.parametrize(
    "action,base,delta,proposed,expected",
    [
        ("INCREASE", "1.20", "0.20", "1.40", []),
        ("INCREASE", "1.20", None, "1.10", ["ACTION_SURGE_MISMATCH"]),
        ("DECREASE", "1.20", None, "1.30", ["ACTION_SURGE_MISMATCH"]),
        ("HOLD", "1.20", None, "1.21", ["ACTION_SURGE_MISMATCH"]),
        ("INCREASE", "1.20", "0.10", "1.40", ["DELTA_MISMATCH"]),
        ("REVIEW", "1.20", None, None, []),
        ("INCREASE", None, None, "1.40", ["SURGE_BASE_MISSING"]),
        ("INCREASE", "1.20", None, None, ["SURGE_PROPOSED_MISSING"]),
    ],
)
def test_consistency(action, base, delta, proposed, expected):
    conv = lambda v: None if v is None else D(v)  # noqa: E731
    assert consistency_errors(action, conv(base), conv(delta), conv(proposed)) == expected


def _elig(policy, **kw):
    args = dict(
        action="INCREASE",
        validation_status="VALID",
        surge_base=D("1.20"),
        surge_proposed=D("1.40"),
        rec_policy_version=policy.policy_version,
        superseded=False,
        policy=policy,
    )
    args.update(kw)
    return evaluate_eligibility(**args)


def test_eligibility_states(policy):
    assert _elig(policy).state == Eligibility.ELIGIBLE
    assert _elig(policy, validation_status="INVALID").state == Eligibility.BLOCKED
    assert _elig(policy, superseded=True).state == Eligibility.SUPERSEDED
    assert _elig(policy, rec_policy_version="other").blocked_reasons == ["POLICY_VERSION_CONFLICT"]
    r = _elig(policy, surge_proposed=D("1.80"))
    assert r.state == Eligibility.BLOCKED and r.blocked_reasons == ["SURGE_LIMIT_EXCEEDED"]


def test_capabilities_by_action(policy):
    assert _elig(policy).capabilities == {"accept": True, "keep_bidding": True, "override": True}
    review = _elig(policy, action="REVIEW", surge_proposed=None)
    assert review.state == Eligibility.ELIGIBLE  # eligibility is independent of action
    assert review.capabilities == {"accept": False, "keep_bidding": False, "override": False}
    hold = _elig(policy, action="HOLD", surge_proposed=D("1.20"))
    assert hold.capabilities == {"accept": False, "keep_bidding": True, "override": policy.allow_hold_override}
    blocked = _elig(policy, validation_status="INVALID")
    assert not any(blocked.capabilities.values())
