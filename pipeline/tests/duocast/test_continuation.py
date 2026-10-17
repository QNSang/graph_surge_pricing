"""Safe continuation, study freeze, artifact manifests and pinned inference."""
from __future__ import annotations

from datetime import timedelta
import json

import pytest
import torch
import yaml

from surge_ml.cli import main
from surge_ml._utils.io import digest_file, trial_lock
from surge_ml.datasets.duocast import load_panel
from surge_ml.datasets.fixtures import make_fixture, write_demo
from surge_ml.inferences.duocast import CheckpointForecastProvider, load_checkpoint
from surge_ml.reports.benchmark import finalize, select
from surge_ml.train.duocast._types import load_config
from surge_ml.train.duocast.train import benchmark, run_trial, trial_folder


@pytest.fixture
def cfg(tmp_path):
    cfg = load_config(write_demo(tmp_path / "input", steps=120, nodes=3))
    cfg.variants = ["persistence", "gru", "duocast"]
    cfg.model.hidden = 8
    cfg.model.head_hidden = 4
    cfg.train.device = "cpu"
    cfg.train.epochs = 1
    cfg.train.limit_batches = 2
    cfg.train.lgbm_rounds = 3
    return cfg


def file_hashes(folder):
    return {str(p.relative_to(folder)): digest_file(p) for p in folder.rglob("*") if p.is_file()}


def test_resume_reuses_completed_and_trains_only_missing_trials(cfg):
    run_trial(cfg, "persistence", 42)
    baseline = trial_folder(cfg, "persistence", 42)
    before = file_hashes(baseline)
    assert len(benchmark(cfg, resume=True)) == 3
    assert file_hashes(baseline) == before
    completed = file_hashes(cfg.output_dir)
    again = benchmark(cfg, resume=True)
    assert len(again) == 3
    assert file_hashes(cfg.output_dir) == completed


def test_resume_recovers_neural_checkpoint_without_completed_result(cfg):
    cfg.variants = ["duocast"]
    run_trial(cfg, "duocast", 42)
    folder = trial_folder(cfg, "duocast", 42)
    (folder / "trial_result.json").unlink()  # Simulate interruption after checkpoint write.
    cfg.train.epochs = 2
    result = benchmark(cfg, resume=True)[0]
    assert result["training"]["epochs_completed"] == 2
    assert load_checkpoint(folder / "last.pt")["epoch"] == 2


def test_interrupted_resume_with_stale_result_can_continue(cfg, monkeypatch):
    import surge_ml.train.duocast.train as training
    cfg.variants = ["persistence", "duocast"]
    benchmark(cfg)
    folder = trial_folder(cfg, "duocast", 42)
    old_result = (folder / "trial_result.json").read_bytes()
    original = training.train_neural
    cfg.train.epochs = 2
    def interrupt_after_checkpoint(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Synthetic interruption after checkpoint, before trial_result")
    monkeypatch.setattr(training, "train_neural", interrupt_after_checkpoint)
    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        benchmark(cfg, resume=True)
    assert (folder / "trial_result.json").read_bytes() == old_result
    assert json.loads((folder / "training_state.json").read_text())["status"] == "RUNNING"
    with pytest.raises(ValueError, match="incomplete"):
        select(cfg)
    monkeypatch.setattr(training, "train_neural", original)
    result = benchmark(cfg, resume=True)[1]
    assert result["training"]["epochs_completed"] == 2
    assert json.loads((folder / "training_state.json").read_text())["status"] == "COMPLETED"
    select(cfg)


def test_unsupported_lightgbm_resume_keeps_completed_state(cfg):
    pytest.importorskip("lightgbm")
    cfg.variants = ["lgbm_local"]
    benchmark(cfg)
    folder = trial_folder(cfg, "lgbm_local", 42)
    before = file_hashes(folder)
    with pytest.raises(ValueError, match="LightGBM resume is not supported"):
        run_trial(cfg, "lgbm_local", 42, resume=True)
    assert file_hashes(folder) == before


def test_resume_extends_neural_epoch_budget(cfg):
    cfg.variants = ["persistence", "duocast"]
    benchmark(cfg)
    before = file_hashes(trial_folder(cfg, "persistence", 42))
    cfg.train.epochs = 2
    results = benchmark(cfg, resume=True)
    assert results[1]["training"]["epochs_completed"] == 2
    assert file_hashes(trial_folder(cfg, "persistence", 42)) == before


@pytest.mark.parametrize("fault", ["missing_manifest", "corrupt_weights", "wrong_identity", "missing_metric"])
def test_resume_rejects_corrupted_completed_trial(cfg, fault):
    cfg.variants = ["duocast"]
    run_trial(cfg, "duocast", 42)
    folder = trial_folder(cfg, "duocast", 42)
    path = folder / "trial_result.json"
    result = json.loads(path.read_text())
    if fault == "missing_manifest":
        result["artifact_sha256"] = {}
    elif fault == "wrong_identity":
        result["seed"] = 43
    elif fault == "missing_metric":
        result["validation"]["overall"].pop("log_ds_rmse")
    else:
        (folder / "best.pt").write_bytes(b"corrupted test-only checkpoint")
    path.write_text(json.dumps(result))
    before = file_hashes(folder)
    with pytest.raises(ValueError):
        benchmark(cfg, resume=True)
    assert file_hashes(folder) == before


def test_partial_lightgbm_is_not_silently_retrained_or_deleted(cfg):
    cfg.variants = ["lgbm_local"]
    folder = trial_folder(cfg, "lgbm_local", 42)
    folder.mkdir(parents=True)
    (folder / "demand_5m.txt").write_text("partial test-only model")
    with pytest.raises(ValueError, match="Cannot resume partial"):
        benchmark(cfg, resume=True)
    assert (folder / "demand_5m.txt").read_text() == "partial test-only model"


def test_shared_study_lock_blocks_training_and_selection(cfg):
    cfg.output_dir.mkdir(parents=True)
    with trial_lock(cfg.output_dir):
        with pytest.raises(ValueError, match="locked"):
            run_trial(cfg, "duocast", 42)
        with pytest.raises(ValueError, match="locked"):
            select(cfg)
    assert not (cfg.output_dir / "duocast").exists()


def test_benchmark_cannot_resume_after_selection(cfg):
    benchmark(cfg)
    select(cfg)
    before = file_hashes(cfg.output_dir)
    with pytest.raises(ValueError, match="frozen"):
        benchmark(cfg, resume=True)
    assert file_hashes(cfg.output_dir) == before


def test_finalize_validates_all_trial_artifacts_before_any_test_output(cfg):
    benchmark(cfg)
    select(cfg)
    last = trial_folder(cfg, "duocast", 42)
    (last / "best.pt").write_bytes(b"corrupted final model")
    with pytest.raises(ValueError, match="artifact"):
        finalize(cfg)
    assert not list(cfg.output_dir.rglob("test_predictions.csv"))
    assert not (cfg.output_dir / "test_report.json").exists()


@pytest.mark.parametrize("change", ["models", "seeds", "winner"])
def test_finalization_cannot_change_the_frozen_experiment(cfg, change):
    benchmark(cfg)
    select(cfg)
    if change == "models":
        cfg.variants = ["persistence", "duocast"]
    elif change == "seeds":
        cfg.seeds = [42, 43]
    else:
        path = cfg.output_dir / "selection.json"
        selection = json.loads(path.read_text())
        selection["selected_variant"] = "not_the_selected_model"
        path.write_text(json.dumps(selection))
    # The manifest hash may reject a changed config before the frozen-list check.
    with pytest.raises(ValueError, match="frozen|Frozen|different data/config"):
        finalize(cfg)
    assert not list(cfg.output_dir.rglob("test_predictions.csv"))


def test_cli_benchmark_resume_flag_reuses_existing_artifacts(cfg, tmp_path):
    cfg.variants = ["persistence"]
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")))
    assert main(["benchmark", "--config", str(path)]) == 0
    before = file_hashes(trial_folder(cfg, "persistence", 42))
    assert main(["benchmark", "--config", str(path), "--resume"]) == 0
    assert file_hashes(trial_folder(cfg, "persistence", 42)) == before


def test_provider_pins_one_checkpoint_revision_and_config(cfg):
    run_trial(cfg, "duocast", 42)
    panel = load_panel(cfg.data)
    fixture = make_fixture(hex_count=panel.n_nodes)
    cutoff = panel.timestamps[-1].to_pydatetime()
    identity = type(fixture.identity).model_validate({**fixture.identity.model_dump(),
        "dataset_id": panel.metadata["dataset_id"], "dataset_fingerprint": panel.fingerprint,
        "node_mapping_version": panel.metadata["node_mapping_version"],
        "feature_version": panel.metadata["feature_definition_version"],
        "cutoff_time": cutoff, "target_time": cutoff + timedelta(minutes=5)})
    path = trial_folder(cfg, "duocast", 42) / "best.pt"
    old_hash = digest_file(path)
    provider = CheckpointForecastProvider(cfg, path, forecast_run_id="pinned-fixture")
    first = provider(identity)
    # A path replacement after construction must not change the artifact used
    # by the existing provider or its reported version/maturity checks.
    path.write_bytes(b"not a checkpoint anymore")
    cfg.data.history = 1  # Caller mutation must not change the provider either.
    second = provider(identity)
    assert first.rows == second.rows
    assert first.checkpoint_version == second.checkpoint_version == old_hash
    assert second.parity_evidence == (f"checkpoint-sha256:{old_hash}",)
    assert second.history_steps == 12
