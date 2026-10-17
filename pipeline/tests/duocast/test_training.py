"""End-to-end model training, artifact identity, resume, CLI, and frozen test access."""
from __future__ import annotations

import json

import numpy as np
import pytest
import torch

from surge_ml.cli import main
from surge_ml.train.duocast._types import load_config
from surge_ml.datasets.fixtures import write_demo
from surge_ml.train.duocast.train import benchmark, prepare, run_trial, trial_folder
from surge_ml.reports.benchmark import collect_results, finalize, report, select
from surge_ml.inferences.duocast import forecast
from surge_ml.inferences.duocast import load_checkpoint


@pytest.fixture
def cfg(tmp_path):
    path = write_demo(tmp_path / "fixture", steps=120, nodes=3)
    cfg = load_config(path)
    cfg.train.device = "cpu"
    cfg.model.hidden = 8
    cfg.variants = ["persistence", "duocast"]
    cfg.model.head_hidden = 4
    cfg.train.epochs = 2
    cfg.train.batch_size = 16
    cfg.train.num_threads = 2
    return cfg


def test_train_to_latest_forecast_then_frozen_final_evaluation(cfg, tmp_path):
    results = benchmark(cfg)
    assert len(results) == 2
    assert not (cfg.output_dir / "test_report.json").exists()
    folder = trial_folder(cfg, "duocast", 42)
    checkpoint = load_checkpoint(folder / "best.pt")
    assert checkpoint["input_schema"]["history"] == 12
    assert checkpoint["input_schema"]["horizon"] == 1
    assert checkpoint["selection_metric"] == "validation.loss_log_huber"
    output = tmp_path / "latest.csv"
    frame = forecast(cfg, folder / "best.pt", output=output)
    assert len(frame) == 3 and output.exists()
    assert set(frame) == {"cutoff_time", "target_time", "hex_id", "pred_demand", "pred_idle_supply", "ds_proxy"}
    assert np.isfinite(frame[["pred_demand", "pred_idle_supply", "ds_proxy"]]).all().all()
    with pytest.raises(ValueError, match="already exists"):
        forecast(cfg, folder / "best.pt", output=output)
    table = report(cfg)
    assert table[0]["loss_log_huber"] <= table[-1]["loss_log_huber"]
    frozen = select(cfg)
    assert frozen["selected_variant"] == table[0]["variant"]
    with pytest.raises(ValueError, match="frozen"):
        run_trial(cfg, "duocast", 42, resume=True)
    final = finalize(cfg)
    assert len(final["trials"]) == 2
    with pytest.raises(ValueError, match="already evaluated"):
        finalize(cfg)
    for trial in final["trials"]:
        metrics = trial["test"]["overall"]
        assert metrics["demand_mae"] >= 0 and metrics["supply_mae"] >= 0


def test_resume_matches_uninterrupted_training(cfg):
    full = cfg.model_copy(deep=True)
    full.output_dir = cfg.output_dir / "full"
    run_trial(full, "duocast", 42)
    interrupted = cfg.model_copy(deep=True)
    interrupted.output_dir = cfg.output_dir / "resumed"
    interrupted.train.epochs = 1
    run_trial(interrupted, "duocast", 42)
    interrupted.train.epochs = 2
    result = run_trial(interrupted, "duocast", 42, resume=True)
    assert result["training"]["epochs_completed"] == 2
    a = load_checkpoint(trial_folder(full, "duocast", 42) / "last.pt")
    b = load_checkpoint(trial_folder(interrupted, "duocast", 42) / "last.pt")
    for name, value in a["model_state"].items():
        torch.testing.assert_close(value, b["model_state"][name], atol=0, rtol=0)
    assert a["best_epoch"] == b["best_epoch"]
    assert a["val_metrics"] == b["val_metrics"]


def test_reject_changed_study_and_legacy_checkpoint(cfg, tmp_path):
    prepare(cfg)
    changed = cfg.model_copy(deep=True)
    changed.train.lr *= 2
    with pytest.raises(ValueError, match="different data/config"):
        prepare(changed)
    path = tmp_path / "legacy.pt"
    torch.save({"model": {}}, path)
    with pytest.raises(ValueError, match="legacy log-ratio"):
        load_checkpoint(path)
    with pytest.raises(ValueError, match="Run select"):
        finalize(cfg)


def test_frozen_artifacts_cannot_be_replaced(cfg):
    benchmark(cfg)
    select(cfg)
    result_path = trial_folder(cfg, "persistence", 42) / "trial_result.json"
    data = json.loads(result_path.read_text())
    data["validation"]["overall"]["demand_mae"] += 1
    result_path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="changed after selection"):
        finalize(cfg)


def test_default_cli_routes_to_geomobinet_and_reports_config_errors(tmp_path, capsys):
    path = tmp_path / "cli-demo"
    assert main(["demo", "--output-dir", str(path), "--steps", "120", "--nodes", "3"]) == 0
    config = path / "config.yaml"
    assert main(["prepare", "--config", str(config)]) == 0
    assert main(["train", "--config", str(config), "--smoke", "--variant", "gru"]) == 0
    checkpoint = path / "runs-smoke" / "gru" / "seed_42" / "best.pt"
    assert checkpoint.is_file()
    assert main(["predict", "--config", str(config), "--checkpoint", str(checkpoint),
                 "--output", str(path / "prediction.csv")]) == 0
    assert main(["select", "--config", str(path / "missing.yaml")]) == 2
    assert "CONFIG" in capsys.readouterr().err


@pytest.mark.parametrize("variant", ["lgbm_local"])
def test_lightgbm_baselines_if_installed(cfg, variant):
    pytest.importorskip("lightgbm")
    cfg.train.lgbm_rounds = 3
    result = run_trial(cfg, variant, 42)
    assert result["validation"]["overall"]["demand_mae"] >= 0
    assert result["test_evaluated"] is False
    assert "demand_5m.txt" in result["artifact_sha256"]
