"""P5/P6 executable synthetic fit-to-decision, replay and next-cycle boundaries."""
from __future__ import annotations
from datetime import timedelta
import json
from surge_ml.ggso.__main__ import main
from surge_ml.ggso.contracts import DecisionResult
from surge_ml.ggso.fixtures import Fixture, make_fitted_fixture, make_fixture


def change(model, **updates):
    return type(model).model_validate({**model.model_dump(), **updates})


def test_p6_complete_fitted_synthetic_chain():
    fixture = make_fitted_fixture()
    calls = []
    result = fixture.run(forecast_provider=fixture.adapter(on_inference=lambda x: calls.append(x)))
    assert result.result_status == "VALID", result.diagnostics
    assert len(calls) == 1
    assert fixture.response.scenario_method == "paired_moving_block_bootstrap.test.v1"
    assert all(cell.calibration.status == "SYNTHETIC_PASS" for cell in fixture.response.cells)
    assert result.production_effective is False


def test_p6_cli_demo_replay_and_no_overwrite(tmp_path):
    folder = tmp_path / "demo"
    assert main(["demo", "--output-dir", str(folder)]) == 0
    before = (folder / "decision.json").read_bytes()
    result = DecisionResult.model_validate_json(before)
    assert result.result_status == "VALID"
    replay = tmp_path / "replayed.json"
    assert main(["replay", "--input", str(folder / "input.json"), "--output", str(replay)]) == 0
    repeated = DecisionResult.model_validate_json(replay.read_bytes())
    assert repeated.optimized_policy == result.optimized_policy
    assert repeated.estimated_metrics == result.estimated_metrics
    assert repeated.selected_candidates == result.selected_candidates
    assert main(["demo", "--output-dir", str(folder)]) == 2
    assert main(["replay", "--input", str(folder / "input.json"), "--output", str(replay)]) == 2
    assert (folder / "decision.json").read_bytes() == before


def test_p6_cli_invalid_emits_empty_diagnostics_envelope(tmp_path):
    payload = make_fixture().payload()
    payload["response"]["semantic_profile_id"] = "unverified-legacy-labels"
    source, target = tmp_path / "invalid_input.json", tmp_path / "invalid_result.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    assert main(["replay", "--input", str(source), "--output", str(target)]) == 2
    result = DecisionResult.model_validate_json(target.read_bytes())
    assert result.result_status == "INVALID" and result.optimized_policy is None and not result.recommendations


def test_p1_executable_schema_export(tmp_path):
    folder = tmp_path / "schemas"
    assert main(["schemas", "--output-dir", str(folder)]) == 0
    paths = list(folder.glob("*.schema.json"))
    assert len(paths) == 7
    for path in paths:
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["properties"]["usage"]["const"] == "TEST_ONLY"
        assert schema["additionalProperties"] is False


def next_cycle_fixture(fixture: Fixture, *, effective_prices: dict[str, str]) -> Fixture:
    """Test-only fresh observations and externally confirmed effective references.

This helper is not a receipt service, does not approve an operator action, and
makes no claim of testing production DB/auth/audit behavior.
"""
    identity = change(fixture.identity, snapshot_id="test-snapshot-002", decision_id="test-decision-002",
                      cutoff_time=fixture.identity.target_time, target_time=fixture.identity.target_time + timedelta(minutes=5),
                      reference_policy_version="test-effective-price-v2")
    rows = tuple(change(row, current_surge=effective_prices.get(row.hex_id, str(row.current_surge)),
                        price_source_version=identity.reference_policy_version, available_at=identity.cutoff_time,
                        quote_window_start=identity.cutoff_time, quote_window_end=identity.target_time,
                        quote_available_at=identity.cutoff_time,
                        capacity=change(row.capacity, available_at=identity.cutoff_time)) for row in fixture.operational.rows)
    operational = change(fixture.operational, identity=identity, rows=rows)
    forecast = change(fixture.forecast, identity=identity, forecast_run_id="test-forecast-run-v2",
                      features_available_at=identity.cutoff_time, generated_at=identity.cutoff_time + timedelta(seconds=1))
    return Fixture(identity, fixture.policy, operational, fixture.response, forecast)


def test_gd07_subset_manual_uses_next_effective_reference_without_immediate_resolve():
    fixture = make_fixture()
    calls = []
    initial = fixture.run(forecast_provider=fixture.adapter(on_inference=lambda i: calls.append(i)))
    original = initial.model_dump_json()
    # One accepted proposal, one manual edit outside the automatic 0.1 action grid.
    prices = {initial.recommendations[0].hex_id: str(initial.recommendations[0].surge_proposed),
              initial.recommendations[1].hex_id: "1.23"}
    following = next_cycle_fixture(fixture, effective_prices=prices)
    assert len(calls) == 1  # Constructing confirmed-reference state does not invoke a model or MILP.
    result = following.run(forecast_provider=following.adapter(on_inference=lambda i: calls.append(i)))
    assert result.result_status == "VALID", result.diagnostics
    assert len(calls) == 2
    assert {r.hex_id: str(r.surge_base) for r in result.recommendations} == prices
    assert result.identity.reference_policy_version == "test-effective-price-v2"
    assert initial.model_dump_json() == original
    assert initial.applied_vector_certified is False
    assert result.applied_vector_certified is False


def test_gd07_invalid_next_cycle_does_not_rollback_confirmed_reference():
    fixture = make_fixture()
    following = next_cycle_fixture(fixture, effective_prices={fixture.identity.required_hex_ids[0]: "1.23"})
    before = following.operational.model_dump_json()
    result = following.run(policy=change(following.policy, br_min=.8, br_max=.9))
    assert result.result_status == "INVALID" and not result.recommendations and result.optimized_policy is None
    assert following.operational.model_dump_json() == before
