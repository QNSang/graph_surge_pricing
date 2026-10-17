"""Preflight validates structure without fitting models or modifying source data."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from surge_ml.cli import main
from surge_ml._utils.io import digest_file
from surge_ml.datasets.fixtures import write_demo
from surge_ml.datasets.preflight import inspect_dataset, main as preflight_main
from surge_ml.train.duocast._types import load_config


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return write_demo(tmp_path / "inputs", steps=120, nodes=3)


def test_preflight_has_complete_evidence_and_no_training_side_effects(config_path):
    cfg = load_config(config_path)
    inputs = (cfg.data.market, cfg.data.spatial, cfg.data.mobility, cfg.data.mobility_snapshots, cfg.data.metadata)
    hashes = {str(path): digest_file(path) for path in inputs}
    result = inspect_dataset(config_path)
    assert result["status"] == "INPUT_STRUCTURE_VALIDATED"
    assert (result["nodes"], result["snapshots"], result["history_steps"]) == (3, 120, 12)
    assert result["observed_empty_mobility_snapshots"] > 0
    assert set(result["input_sha256"]) == {"market", "spatial", "mobility", "mobility_snapshots", "metadata"}
    assert set(result["split_manifest"]) == {"train", "val", "test"}
    assert result["production_eligible"] is False
    assert result["source_semantics_verified"] is False
    assert not cfg.output_dir.exists()
    assert hashes == {str(path): digest_file(path) for path in inputs}


def test_main_cli_preflight_and_standalone_agree(config_path, tmp_path, capsys):
    output = tmp_path / "checks" / "preflight.json"
    assert main(["preflight", "--config", str(config_path), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert json.loads(capsys.readouterr().out) == report
    assert preflight_main(["--config", str(config_path)]) == 0
    assert json.loads(capsys.readouterr().out) == report
    before = output.read_bytes()
    assert main(["preflight", "--config", str(config_path), "--output", str(output)]) == 2
    assert output.read_bytes() == before


@pytest.mark.parametrize("fault", ["fractional", "missing_coverage", "late_feature", "wrong_semantics"])
def test_bad_input_fails_without_creating_report(config_path, tmp_path, fault):
    cfg = load_config(config_path)
    if fault == "wrong_semantics":
        meta = json.loads(cfg.data.metadata.read_text())
        meta["demand_definition"] = "quotes"
        cfg.data.metadata.write_text(json.dumps(meta))
    elif fault == "missing_coverage":
        frame = pd.read_csv(cfg.data.mobility_snapshots)
        frame.iloc[1:].to_csv(cfg.data.mobility_snapshots, index=False)
    else:
        frame = pd.read_csv(cfg.data.market)
        if fault == "fractional":
            frame["demand_5m"] = frame["demand_5m"].astype(float)
            frame.loc[0, "demand_5m"] = 1.5
        else:
            frame.loc[0, "available_at"] = "2030-01-01T00:00:00+07:00"
        frame.to_csv(cfg.data.market, index=False)
    output = tmp_path / "should_not_exist.json"
    assert main(["preflight", "--config", str(config_path), "--output", str(output)]) == 2
    assert not output.exists()
    assert not cfg.output_dir.exists()


def test_missing_configuration_is_an_actionable_cli_error(tmp_path, capsys):
    assert main(["preflight", "--config", str(tmp_path / "missing.yaml")]) == 2
    assert "Config not found" in capsys.readouterr().err
