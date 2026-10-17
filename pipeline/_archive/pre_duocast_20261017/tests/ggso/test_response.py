"""P2: likelihood convention, bounded fitting, chronological support and artifacts."""
from __future__ import annotations
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
import numpy as np
import pytest
from scipy.stats import binom, nbinom
from surge_ml.ggso.contracts import ResponseArtifact, Scenario, Vector
from surge_ml.ggso.errors import GGSOError
from surge_ml.ggso.fixtures import fit_config, make_fixture, synthetic_observations
from surge_ml.ggso.response import bootstrap
from surge_ml.ggso.response.artifacts import fit_artifact, load_artifact, save_artifact
from surge_ml.ggso.response.dataset import Arrays, Observation, chronological_split
from surge_ml.ggso.response.glm import binomial_nll, fit_demand, fit_fulfillment, nb_nll


def change(model, **updates):
    return type(model).model_validate({**model.model_dump(), **updates})


def test_rm_nb2_likelihood_matches_scipy_parameter_mapping():
    d = np.array([0, 1, 10, 100])
    mu = np.array([.1, 1, 12, 85])
    k = 7.0
    assert nb_nll(d, np.log(mu), k) == pytest.approx(-nbinom.logpmf(d, k, k / (k + mu)), abs=1e-10)


def test_rm_binomial_likelihood_and_zero_trials():
    d, c = np.array([0, 1, 10, 100]), np.array([0, 1, 3, 65])
    p = np.array([.5, .6, .3, .65])
    assert binomial_nll(d, c, np.log(p / (1 - p))) == pytest.approx(-binom.logpmf(c, d, p), abs=1e-10)
    assert binomial_nll([0], [0], [1000.0])[0] == 0
    assert np.isfinite(binomial_nll([10, 10], [0, 10], [-1000.0, 1000.0])).all()


@pytest.mark.parametrize("d,c", [([1.2], [0]), ([1], [2]), ([-1], [0]), ([0], [1]), ([True], [0]), ([float('nan')], [0])])
def test_rm_invalid_cohort_counts(d, c):
    with pytest.raises(ValueError):
        binomial_nll(d, c, [0.0])


def test_rm_controlled_synthetic_parameter_recovery():
    rows = synthetic_observations(n=1800)
    d = np.array([r.booking_demand for r in rows])
    c = np.array([r.completed_bookings for r in rows])
    s = np.array([float(r.applied_surge) for r in rows])
    k = np.array([r.effective_capacity for r in rows])
    x = np.array([r.demand_context.values for r in rows])
    config = fit_config(replicas=2)
    demand = fit_demand(d, s, x, config)
    fulfillment = fit_fulfillment(d, c, k, x, config)
    assert demand.intercept == pytest.approx(3.0, abs=.15)
    assert demand.beta == pytest.approx(1.2, abs=.2)
    assert demand.coefficients[0] == pytest.approx(.25, abs=.1)
    assert demand.dispersion == pytest.approx(8.0, abs=2.0)
    assert fulfillment.intercept == pytest.approx(.2, abs=.1)
    assert fulfillment.gamma == pytest.approx(.55, abs=.1)
    assert fulfillment.coefficients[0] == pytest.approx(-.1, abs=.1)
    assert 0 <= demand.beta <= 4 and 0 <= fulfillment.gamma <= 1


def test_rm_train_only_scaling_and_context_order():
    rows = synthetic_observations(n=120)
    split = rows[90].decision_time
    mutated = [*rows[:90], *(change(r, demand_context=change(r.demand_context, values=(100000.0,))) for r in rows[90:])]
    train, val, train_arrays, val_arrays, td, tf = chronological_split(mutated, split, rows[-1].outcome_matured_at)
    assert td.mean[0] == pytest.approx(np.mean([r.demand_context.values[0] for r in rows[:90]]))
    assert val_arrays.demand_context.mean() > 10000
    with pytest.raises(ValueError, match="schema"):
        td.apply(Vector(names=("wrong_feature",), values=(0.0,), schema_version=td.schema_version))


@pytest.mark.parametrize("fault", ["future_feature", "immature", "wrong_cohort", "fractional", "completion_gt_d", "overlapping_maturity"])
def test_rm_observation_point_in_time_faults(fault):
    rows = synthetic_observations(n=120)
    data = rows[0].model_dump()
    if fault == "future_feature": data["feature_available_at"] = rows[0].target_time
    elif fault == "immature": data["outcome_matured_at"] = rows[0].decision_time
    elif fault == "wrong_cohort": data["cohort_profile"] = "all_completions_in_interval"
    elif fault == "fractional": data["booking_demand"] = 1.5
    elif fault == "completion_gt_d": data["completed_bookings"] = data["booking_demand"] + 1
    elif fault == "overlapping_maturity":
        rows[0] = change(rows[0], outcome_matured_at=rows[91].target_time)
        with pytest.raises(GGSOError, match="boundary"):
            chronological_split(rows, rows[90].decision_time, rows[-1].outcome_matured_at)
        return
    with pytest.raises(ValueError):
        Observation.model_validate(data)


def test_ra_fit_bootstrap_serialization_and_refuse_overwrite(tmp_path):
    rows = synthetic_observations(n=360)
    config = fit_config(replicas=3)
    kwargs = dict(required_hex_ids=("test-hex-00",), split_time=rows[270].decision_time,
                  fit_as_of=rows[-1].outcome_matured_at, dataset_id="synthetic-response-data-v1",
                  node_mapping_version="test-node-order-v1", artifact_version="synthetic-fitted-artifact-v1", config=config)
    artifact = fit_artifact(rows, **kwargs)
    assert artifact.cells[0].calibration.status == "SYNTHETIC_PASS"
    assert artifact.scenario_method == "paired_moving_block_bootstrap.test.v1"
    assert len(artifact.cells[0].scenarios) == config.bootstrap_replicates
    assert artifact.production_eligible is False
    path = tmp_path / "response.json"
    save_artifact(artifact, path)
    assert load_artifact(path) == artifact
    assert ResponseArtifact.model_validate_json(artifact.model_dump_json()) == artifact
    with pytest.raises(FileExistsError):
        save_artifact(artifact, path)
    repeat = fit_artifact(rows, **kwargs)
    assert repeat == artifact


def test_ra_failed_calibration_is_ineligible_not_auto_approved():
    rows = synthetic_observations(n=240)
    config = change(fit_config(replicas=1), max_demand_mean_nll=.001)
    artifact = fit_artifact(rows, required_hex_ids=("test-hex-00",), split_time=rows[180].decision_time,
                            fit_as_of=rows[-1].outcome_matured_at, dataset_id="synthetic",
                            node_mapping_version="test-nodes", artifact_version="synthetic-ineligible", config=config)
    assert artifact.cells[0].fit_status == "CONVERGED"
    assert artifact.cells[0].calibration.status == "INELIGIBLE"
    assert "HELD_OUT_NB_NLL" in artifact.cells[0].calibration.rejection_reasons


def test_ra_bootstrap_preserves_pairing_and_failed_replicates(monkeypatch):
    config = fit_config(replicas=3)
    d = np.arange(60, dtype=float)
    arrays = Arrays(demand=d, completed=d, surge=d + 1, capacity=d + 1,
                    demand_context=d[:, None], fulfillment_context=d[:, None])
    calls = []
    def demand_fit(demand, surge, context, config):
        calls.append(demand.copy())
        assert np.array_equal(surge - 1, demand)
        assert np.array_equal(context[:, 0], demand)
        return SimpleNamespace(beta=1.0)
    def fulfillment_fit(demand, completed, capacity, context, config):
        assert np.array_equal(demand, calls[-1])
        assert np.array_equal(demand, completed)
        assert np.array_equal(demand, capacity - 1)
        return SimpleNamespace(gamma=.5)
    monkeypatch.setattr(bootstrap, "fit_demand", demand_fit)
    monkeypatch.setattr(bootstrap, "fit_fulfillment", fulfillment_fit)
    scenarios = bootstrap.paired_scenarios(arrays, config, "test-cell")
    assert len(calls) == len(scenarios) == 3
    def failed(*args, **kwargs):
        raise ValueError("synthetic failure")
    monkeypatch.setattr(bootstrap, "fit_demand", failed)
    with pytest.raises(GGSOError, match="replicate 0"):
        bootstrap.paired_scenarios(arrays, config, "test-cell")


@pytest.mark.parametrize("fault", ["weights", "count", "bounds", "order", "convention"])
def test_ra_artifact_contract_faults(fault):
    data = make_fixture().response.model_dump(mode="json")
    if fault == "weights": data["cells"][0]["scenarios"][0]["weight"] = .9
    elif fault == "count": data["cells"][0]["scenarios"].pop()
    elif fault == "bounds": data["cells"][0]["gamma"] = 2.0
    elif fault == "order": data["cells"].reverse()
    elif fault == "convention": data["nb_parameterization"] = "unspecified"
    with pytest.raises(ValueError):
        ResponseArtifact.model_validate(data)
