"""P1/P3/P4/P5/P6 synthetic acceptance: DT, MI, CS, MO, CP and DP."""
from __future__ import annotations
import itertools
from datetime import timedelta
from decimal import Decimal
import numpy as np
import pytest
from surge_ml.inferences.schemas import PolicyConfig
from surge_ml.contracts import (CandidateTable, CapacitySource, DecisionResult, Forecast,
                                     OperationalSnapshot, ResponseArtifact, Scenario)
from surge_ml.errors import GGSOError
from surge_ml.datasets.fixtures import make_fixture
from surge_ml.inferences.schemas import prepare_network
from surge_ml.inferences.network_optimizer import SolveAttempt, solve
from surge_ml.inferences.network_optimizer import build_problem
from surge_ml.inferences.validator import validate_selection
from surge_ml.inferences.candidate_utility import capacity_value
from surge_ml.inferences.candidate_utility import GRID, build_candidates, evaluate_candidate, outcome


def change(model, **updates):
    return type(model).model_validate({**model.model_dump(), **updates})


def assert_invalid(result):
    assert result.result_status == "INVALID", result
    assert result.recommendations == ()
    assert result.selected_candidates == ()
    assert result.optimized_policy is None
    assert result.estimated_metrics is None
    assert result.constraint_checks is None
    assert result.publication == "NOT_REQUESTED"
    assert result.production_effective is False
    assert result.production_eligible is False
    assert result.error_code


@pytest.mark.parametrize("count", [1, 2, 3])
def test_dp_valid_complete_and_roundtrip(count):
    fixture = make_fixture(hex_count=count)
    calls = []
    result = fixture.run(forecast_provider=fixture.adapter(on_inference=lambda identity: calls.append(identity)))
    assert result.result_status == "VALID", result.diagnostics
    assert len(calls) == 1
    assert tuple(result.optimized_policy) == fixture.identity.required_hex_ids
    assert all(r.action == "INCREASE" and r.surge_delta == Decimal("0.3") for r in result.recommendations)
    assert result.estimated_metrics.nominal_incremental_gmv >= 0
    assert result.production_eligible is result.production_effective is result.applied_vector_certified is False
    assert DecisionResult.model_validate_json(result.model_dump_json()) == result
    replay = fixture.run()
    assert replay.optimized_policy == result.optimized_policy
    assert replay.estimated_metrics == result.estimated_metrics
    assert replay.selected_candidates == result.selected_candidates


def test_cs_golden_arithmetic():
    network = make_fixture(hex_count=1).network()
    baseline = outcome(network, 0, Decimal("1.2"), 0.0, 0.0)
    candidate = evaluate_candidate(network, 0, Decimal("0.1"))
    assert baseline.expected_gmv == pytest.approx(600)
    assert candidate.outcome.fulfillment_rate == 0.5
    assert candidate.outcome.expected_completed == 5
    assert candidate.outcome.expected_gmv == pytest.approx(650)
    assert candidate.incremental_gmv == pytest.approx(50)
    assert candidate.conservative_utility == pytest.approx(50)
    assert candidate.proposed_surge == Decimal("1.3")
    hold = evaluate_candidate(network, 0, Decimal("0"))
    assert hold.incremental_gmv == hold.conservative_utility == 0
    assert hold.scenario_increments == (0.0, 0.0, 0.0)


def test_cs_pair_scenario_baselines_not_nominal():
    fixture = make_fixture(hex_count=1, beta=1.2, gamma=0.3)
    scenarios = tuple(Scenario(scenario_id=f"scenario-{i}", beta=1.2, gamma=float(gamma), weight=1/3)
                      for i, gamma in enumerate([0, 0.5, 1]))
    cell = change(fixture.response.cells[0], scenarios=scenarios)
    response = change(fixture.response, cells=(cell,))
    network = prepare_network(fixture.forecast, fixture.operational, response, fixture.policy)
    candidate = evaluate_candidate(network, 0, Decimal("0.1"))
    paired = [outcome(network, 0, Decimal("1.3"), s.beta, s.gamma).expected_gmv
              - outcome(network, 0, Decimal("1.2"), s.beta, s.gamma).expected_gmv for s in scenarios]
    assert candidate.scenario_increments == pytest.approx(paired)
    assert candidate.conservative_utility == pytest.approx(np.quantile(paired, .05, method="linear"))
    nominal_baseline = outcome(network, 0, Decimal("1.2"), cell.beta, cell.gamma).expected_gmv
    wrong = [outcome(network, 0, Decimal("1.3"), s.beta, s.gamma).expected_gmv - nominal_baseline for s in scenarios]
    assert not np.isclose(candidate.conservative_utility, np.quantile(wrong, .05))


@pytest.mark.parametrize("unit,eta", [("minutes", 10.0), ("seconds", 600.0)])
def test_cs_capacity_units(unit, eta):
    source = make_fixture().operational.rows[0].capacity
    source = change(source, method="GGSO_IDLE_APPROXIMATION", direct_capacity=None,
                    rides_per_driver_hour=6.0, eta=eta, eta_unit=unit)
    assert capacity_value(12.0, source) == pytest.approx(3.0)
    assert capacity_value(0.0, source) == 0


@pytest.mark.parametrize("zero", ["demand", "capacity"])
def test_cs_zero_demand_or_capacity(zero):
    fixture = make_fixture(hex_count=1)
    forecast, operational = fixture.forecast, fixture.operational
    if zero == "demand":
        forecast = change(forecast, rows=(change(forecast.rows[0], forecast_demand=0.0),))
    else:
        row = operational.rows[0]
        operational = change(operational, rows=(change(row, capacity=change(row.capacity, direct_capacity=0.0)),))
    network = prepare_network(forecast, operational, fixture.response, fixture.policy)
    table = build_candidates(network)
    assert all(c.outcome.expected_gmv == 0 and c.outcome.expected_completed == 0 for c in table.candidates)


def test_cs_bounds_are_rejected_not_clamped():
    table = build_candidates(make_fixture(hex_count=1).network())
    assert len(table.candidates) == 6
    assert [(r.action, r.proposed_surge) for r in table.rejected] == [(Decimal("-0.3"), Decimal("0.9"))]
    assert len({c.proposed_surge for c in table.candidates}) == len(table.candidates)
    assert CandidateTable.model_validate_json(table.model_dump_json()) == table


def test_cs_baseline_separate_when_zero_out_of_policy():
    fixture = make_fixture(hex_count=1)
    policy = change(fixture.policy, surge_min="1.3")
    network = prepare_network(fixture.forecast, fixture.operational, fixture.response, policy)
    table = build_candidates(network)
    assert all(c.action > 0 for c in table.candidates)
    assert min(c.incremental_gmv for c in table.candidates) == pytest.approx(50)


def test_cs_demand_above_quotes_is_rejected_not_clipped():
    fixture = make_fixture(hex_count=1, beta=4.0)
    operational = change(fixture.operational, rows=(change(fixture.operational.rows[0], quote_opportunities=10.0),))
    network = prepare_network(fixture.forecast, operational, fixture.response, fixture.policy)
    table = build_candidates(network)
    assert any("DEMAND_EXCEEDS_QUOTES" in r.reasons for r in table.rejected)
    assert all(c.outcome.expected_demand <= 10 for c in table.candidates)


@pytest.mark.parametrize("count,beta,gamma,spatial", [(2, 0.0, 0.0, 0.0), (2, 1.2, .6, 200.0), (3, 2.0, .4, 5.0)])
def test_mo_compare_against_independent_exhaustive_oracle(count, beta, gamma, spatial):
    fixture = make_fixture(hex_count=count, beta=beta, gamma=gamma)
    policy = change(fixture.policy, lambda_spatial=spatial)
    network = prepare_network(fixture.forecast, fixture.operational, fixture.response, policy)
    table = build_candidates(network)
    groups = [[c for c in table.candidates if c.hex_id == node] for node in fixture.identity.required_hex_ids]
    quotes = sum(row.quote_opportunities for row in fixture.operational.rows)
    feasible = []
    for selected in itertools.product(*groups):
        br = sum(c.outcome.expected_demand for c in selected) / quotes
        delta = sum(c.incremental_gmv for c in selected)
        if not policy.br_min <= br <= policy.br_max or delta < -policy.money_tolerance:
            continue
        prices = {c.hex_id: c.proposed_surge for c in selected}
        objective = sum(c.conservative_utility - policy.lambda_temporal * float(abs(c.action)) for c in selected)
        objective -= policy.lambda_spatial * sum(e.weight * float(abs(prices[e.source] - prices[e.target]))
                                                for e in fixture.operational.pricing_edges)
        feasible.append(objective)
    result = fixture.run(policy=policy)
    assert result.result_status == "VALID", result.diagnostics
    assert result.estimated_metrics.objective == pytest.approx(max(feasible), abs=1e-6)


def test_mo_hold_can_be_br_infeasible():
    fixture = make_fixture()
    policy = change(fixture.policy, br_min=.8, br_max=.9)
    result = fixture.run(policy=policy)
    assert_invalid(result)
    assert result.solver.raw_status == 2


def test_mo_hard_nominal_no_loss_rejects_negative_selected_vector():
    network = make_fixture().network()
    table = build_candidates(network)
    ids = tuple(next(c.candidate_id for c in table.candidates if c.hex_id == node and c.action == Decimal("-0.1"))
                for node in network.identity.required_hex_ids)
    with pytest.raises(GGSOError, match="no-loss"):
        validate_selection(network, table, ids)


def test_mo_rejects_corrupted_candidates_even_with_same_ids():
    network = make_fixture().network()
    table = build_candidates(network)
    corrupt = change(table.candidates[0], incremental_gmv=table.candidates[0].incremental_gmv + 1000)
    corrupted_table = change(table, candidates=(corrupt, *table.candidates[1:]))
    ids = tuple(next(c.candidate_id for c in table.candidates if c.hex_id == node and c.action == 0)
                for node in network.identity.required_hex_ids)
    with pytest.raises(GGSOError, match="recomputation"):
        validate_selection(network, corrupted_table, ids)


@pytest.mark.parametrize("fault", ["limit_with_incumbent", "limit_without_incumbent", "fractional", "wrong_shape", "unknown_status", "solver_exception"])
def test_mo_solver_status_and_fault_matrix(fault):
    fixture = make_fixture()
    def injected(problem, policy):
        if fault == "solver_exception":
            raise RuntimeError("TEST_ONLY injected solver crash")
        attempt = solve(problem, policy)
        if fault.startswith("limit"):
            info = change(attempt.info, raw_status=1, message="TEST_ONLY injected limit", mip_gap=None, dual_bound=None)
            return SolveAttempt(info, attempt.x if fault == "limit_with_incumbent" else None)
        if fault == "unknown_status":
            return SolveAttempt(change(attempt.info, raw_status=4), attempt.x)
        x = attempt.x.copy()
        if fault == "fractional":
            x[0] = .5
        else:
            x = x[:-1]
        return SolveAttempt(attempt.info, x)
    result = fixture.run(solve_fn=injected)
    if fault == "limit_with_incumbent":
        assert result.result_status == "VALID", result.diagnostics
        assert result.solver.accepted_status == "FEASIBLE_LIMIT"
        assert result.solver.mip_gap is None and result.solver.dual_bound is None
    else:
        assert_invalid(result)


@pytest.mark.parametrize("fault", ["missing_q", "zero_q", "null_q", "future_q", "realized_q", "missing_cell",
    "duplicate_cell", "nonfinite_fare", "wrong_currency", "recorded_price", "price_version", "wrong_target",
    "missing_response", "response_future", "response_ineligible", "wrong_profile", "no_candidates", "official_mode"])
def test_dp_fail_closed_input_matrix(fault):
    fixture = make_fixture()
    ops = fixture.operational.model_dump(mode="json")
    response = fixture.response.model_dump(mode="json")
    policy = fixture.policy.model_dump(mode="json")
    row = ops["rows"][0]
    if fault == "missing_q": del row["quote_opportunities"]
    elif fault == "zero_q":
        for r in ops["rows"]: r["quote_opportunities"] = 0.0
    elif fault == "null_q": row["quote_opportunities"] = None
    elif fault == "future_q": row["quote_available_at"] = fixture.identity.target_time.isoformat()
    elif fault == "realized_q": row["quote_source_kind"] = "REALIZED_FUTURE"
    elif fault == "missing_cell": ops["rows"].pop()
    elif fault == "duplicate_cell": ops["rows"][1] = row
    elif fault == "nonfinite_fare": row["reference_fare"] = float("nan")
    elif fault == "wrong_currency": ops["currency"] = "OTHER"
    elif fault == "recorded_price": row["price_state"] = "RECORDED"
    elif fault == "price_version": row["price_source_version"] = "pending-new-price"
    elif fault == "wrong_target": row["quote_window_end"] = (fixture.identity.target_time + timedelta(minutes=5)).isoformat()
    elif fault == "missing_response": response["cells"].pop()
    elif fault == "response_future": response["available_at"] = fixture.identity.target_time.isoformat()
    elif fault == "response_ineligible":
        response["cells"][0]["calibration"].update(status="INELIGIBLE", rejection_reasons=["TEST_CALIBRATION_FAILED"])
    elif fault == "wrong_profile": response["semantic_profile_id"] = "eligible-requests-unverified"
    elif fault == "no_candidates": response["cells"][0]["support"].update(surge_min="1.7", surge_max="2.5")
    elif fault == "official_mode": policy["usage"] = "PRODUCTION"
    assert_invalid(fixture.run(operational=ops, response=response, policy=policy))


@pytest.mark.parametrize("fault", ["missing_node", "order", "negative", "wrong_demand_definition", "future_features", "wrong_checkpoint"])
def test_mi_forecast_faults(fault):
    fixture = make_fixture()
    forecast = fixture.forecast.model_dump(mode="json")
    if fault == "missing_node": forecast["rows"].pop()
    elif fault == "order": forecast["rows"].reverse()
    elif fault == "negative": forecast["rows"][0]["forecast_demand"] = -1.0
    elif fault == "wrong_demand_definition": forecast["demand_definition"] = "eligible_requests"
    elif fault == "future_features": forecast["features_available_at"] = fixture.identity.target_time.isoformat()
    elif fault == "wrong_checkpoint": forecast["checkpoint_contract"] = "legacy_ratio_v1"
    assert_invalid(fixture.run(forecast_provider=lambda _: forecast))


def test_cp_invalid_cannot_be_serialized_with_fake_hold_policy():
    fixture = make_fixture()
    result = fixture.run(policy=change(fixture.policy, br_min=.8, br_max=.9))
    data = result.model_dump()
    data["optimized_policy"] = {node: "1.2" for node in fixture.identity.required_hex_ids}
    with pytest.raises(ValueError):
        DecisionResult.model_validate(data)


def test_dt_duplicate_reverse_edge_and_ambiguous_capacity_rejected():
    fixture = make_fixture()
    edge = fixture.operational.pricing_edges[0]
    with pytest.raises(ValueError):
        change(fixture.operational, pricing_edges=(edge, change(edge, source=edge.target, target=edge.source)))
    with pytest.raises(ValueError):
        change(fixture.operational.rows[0].capacity, rides_per_driver_hour=6.0)
