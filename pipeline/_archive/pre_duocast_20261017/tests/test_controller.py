import numpy as np
import pytest
from pydantic import ValidationError

from surge_ml.config import ControllerConfig
from surge_ml.controller import apply_surge_controller, dead_zone


def _run(q_local, q_graph, bidding=1.3, **overrides):
    cfg = ControllerConfig(**overrides)
    return apply_surge_controller(np.log(np.asarray(q_local)), np.log(np.asarray(q_graph)), bidding, cfg)


def test_dead_zone_preserves_sign_and_removes_threshold():
    values = dead_zone(np.array([-0.2, -0.05, 0.0, 0.1, 0.3]), 0.1)
    np.testing.assert_allclose(values, [-0.1, 0.0, 0.0, 0.0, 0.2])


def test_worked_example_network_revision_reduces_pressure_correction():
    out = _run([2.0], [1.6])
    assert out["pressure"][0] == pytest.approx(1 / 3)
    assert out["revision"][0] == pytest.approx(-0.2)
    assert out["delta_requested"][0] == pytest.approx(0.08)
    assert out["final_surge"][0] == pytest.approx(1.38)
    assert out["status"][0] == "INCREASE"
    assert out["reason"][0] == "PRESSURE_REVISION"


def test_requested_and_global_caps_are_separate():
    out = _run([1.4], [2.4], bidding=[1.3], surge_max=1.5)
    assert out["delta_requested"][0] == pytest.approx(0.4)
    assert out["final_surge"][0] == pytest.approx(1.5)
    assert out["delta_applied"][0] == pytest.approx(0.2)
    assert bool(out["requested_capped"][0]) and bool(out["global_capped"][0])
    assert out["reason"][0] == "GLOBAL_CAP"


def test_direction_gate_and_pressure_dead_zone_hold():
    out = _run([2.0, 0.8], [1.35, 1.2])
    np.testing.assert_allclose(out["delta_requested"], [0.0, 0.0], atol=1e-12)
    assert out["reason"].tolist() == ["DIRECTION_BLOCKED", "PRESSURE_DEAD_ZONE"]
    assert out["status"].tolist() == ["HOLD", "HOLD"]


def test_invalid_forecast_reviews_and_preserves_valid_bidding():
    cfg = ControllerConfig()
    out = apply_surge_controller(np.array([np.nan, -1000.0]), np.array([0.0, 0.0]), np.array([1.4, 1.5]), cfg)
    assert out["status"].tolist() == ["REVIEW", "REVIEW"]
    assert out["reason"].tolist() == ["NONFINITE_FORECAST", "LOCAL_BELOW_Q_MIN"]
    np.testing.assert_allclose(out["final_surge"], [1.4, 1.5])
    np.testing.assert_allclose(out["delta_requested"], [0.0, 0.0])


def test_invalid_bidding_is_not_hidden_by_clipping():
    out = _run([1.2, 1.2], [1.6, 1.6], bidding=[0.9, np.nan])
    assert out["status"].tolist() == ["REVIEW", "REVIEW"]
    assert out["reason"].tolist() == ["INVALID_BIDDING", "INVALID_BIDDING"]
    assert np.isnan(out["final_surge"]).all()
    assert np.isnan(out["delta_applied"]).all()


def test_policy_rejects_unsafe_or_unverified_configuration():
    with pytest.raises(ValidationError, match="max_requested_delta"):
        ControllerConfig(max_requested_delta=0.5)
    with pytest.raises(ValidationError, match="not supported"):
        ControllerConfig(calibrated=True)


def test_scalar_input_is_supported():
    out = _run(2.0, 1.6)

    assert float(out["final_surge"]) == pytest.approx(1.38)
    assert out["status"].item() == "INCREASE"
