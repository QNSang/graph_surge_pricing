"""Response diagnostics remain separate from fitting objectives and approval gates."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from surge_ml.cli import main
from surge_ml._utils.io import digest_file
from surge_ml.datasets.fixtures import synthetic_observations, fit_config
from surge_ml.reports.responses import fulfillment_diagnostics
from surge_ml.train.responses.train import fit_from_config, load_artifact


def test_bins_reveal_errors_hidden_by_aggregate_calibration():
    result = fulfillment_diagnostics([10, 10], [9, 1], [0.1, 0.9])
    assert result["calibration_in_the_large"] == pytest.approx(0)
    assert result["booking_weighted_ece"] == pytest.approx(0.8)
    assert result["booking_weighted_brier"] == pytest.approx(0.73)
    assert sum(row["booking_trials"] for row in result["probability_bins"]) == 20


def test_zero_trials_have_null_rates_not_perfect_scores():
    result = fulfillment_diagnostics([0, 0], [0, 0], [0.0, 1.0])
    assert result["booking_trials"] == 0
    assert result["booking_weighted_brier"] is None
    assert result["booking_weighted_ece"] is None
    assert result["calibration_in_the_large"] is None
    assert all(row["absolute_gap"] is None for row in result["probability_bins"])


def test_probability_endpoints_are_included_once():
    result = fulfillment_diagnostics([2, 3], [0, 3], [0.0, 1.0])
    assert result["booking_weighted_brier"] == 0
    assert result["probability_bins"][0]["booking_trials"] == 2
    assert result["probability_bins"][-1]["booking_trials"] == 3


@pytest.mark.parametrize("d,c,p", [([1], [2], [0.5]), ([1.5], [1], [0.5]),
    ([1], [0], [-0.1]), ([1], [0], [float("nan")]), ([1, 2], [0], [0.2])])
def test_invalid_diagnostic_inputs_are_rejected(d, c, p):
    with pytest.raises(ValueError):
        fulfillment_diagnostics(d, c, p)


@pytest.fixture
def job_path(tmp_path: Path) -> Path:
    rows = synthetic_observations(n=120)
    source = tmp_path / "observations.json"
    source.write_text(json.dumps([row.model_dump(mode="json") for row in rows]), encoding="utf-8")
    job = dict(input="observations.json", output="fitted/artifact.json", report="fitted/calibration.json",
               dataset_id="synthetic-report", node_mapping_version="test-nodes",
               required_hex_ids=["test-hex-00"], artifact_version="report-fixture-v1",
               split_time=rows[90].decision_time.isoformat(), fit_as_of=rows[-1].outcome_matured_at.isoformat(),
               fit=fit_config(replicas=1).model_dump(mode="json"))
    path = tmp_path / "fit.yaml"
    path.write_text(yaml.safe_dump(job), encoding="utf-8")
    return path


def test_fit_emits_report_bound_to_artifact_without_changing_gates(job_path):
    result = fit_from_config(job_path)
    artifact = load_artifact(Path(result["path"]))
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["production_eligible"] is False
    assert report["eligibility_gate_changed"] is False
    assert report["artifact_sha256"] == digest_file(Path(result["path"]))
    assert report["input_sha256"] == digest_file(job_path.parent / "observations.json")
    row = report["cells"][0]
    assert row["calibration_status"] == artifact.cells[0].calibration.status
    assert row["held_out"]["demand_mean_nll"] == pytest.approx(artifact.cells[0].calibration.demand_mean_nll)
    assert row["held_out"]["fulfillment_mean_nll"] == pytest.approx(artifact.cells[0].calibration.fulfillment_mean_nll)
    assert row["within_training_support"] + row["outside_training_support"] == 30
    assert row["by_surge"] and row["scenario_count"] == 1
    with pytest.raises(FileExistsError):
        fit_from_config(job_path)


@pytest.mark.parametrize("bad_job", [None, [], {"unexpected_field": True}])
def test_invalid_job_is_a_cli_error_not_an_uncaught_attribute_error(job_path, bad_job, capsys):
    job_path.write_text(yaml.safe_dump(bad_job))
    assert main(["fit-responses", "--config", str(job_path)]) == 2
    assert "ValidationError" in capsys.readouterr().err
    assert not (job_path.parent / "fitted").exists()


def test_report_destination_collision_fails_before_fitting(job_path):
    job = yaml.safe_load(job_path.read_text())
    job["report"] = job["output"]
    job_path.write_text(yaml.safe_dump(job))
    with pytest.raises(ValueError, match="distinct"):
        fit_from_config(job_path)
    assert not (job_path.parent / "fitted").exists()


def test_existing_report_is_not_overwritten_or_followed_by_a_new_fit(job_path, monkeypatch):
    import surge_ml.train.responses.train as trainer
    report = job_path.parent / "fitted" / "calibration.json"
    report.parent.mkdir()
    report.write_text("existing diagnostic report")
    def forbidden(*args, **kwargs):
        raise AssertionError("Must check output conflicts before fitting")
    monkeypatch.setattr(trainer, "fit_artifact", forbidden)
    with pytest.raises(FileExistsError):
        fit_from_config(job_path)
    assert report.read_text() == "existing diagnostic report"
    assert not report.with_name("artifact.json").exists()


def test_changed_source_during_fitting_is_not_published(job_path, monkeypatch):
    import surge_ml.train.responses.train as trainer
    original = trainer.fit_artifact
    def mutate_source(*args, **kwargs):
        artifact = original(*args, **kwargs)
        with (job_path.parent / "observations.json").open("a") as stream:
            stream.write("\n")
        return artifact
    monkeypatch.setattr(trainer, "fit_artifact", mutate_source)
    with pytest.raises(ValueError, match="changed while fitting"):
        fit_from_config(job_path)
    assert not (job_path.parent / "fitted" / "artifact.json").exists()
