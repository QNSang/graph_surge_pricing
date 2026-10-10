import pytest
import yaml

from surge_ml.cli import main
from surge_ml.config import apply_overrides, config_sha256, load_config
from surge_ml.errors import SurgeError
from surge_ml.tracking.mlflow_adapter import Tracker
from conftest import write_config


def test_unknown_key_rejected(tmp_path):
    path = write_config(tmp_path)
    raw = yaml.safe_load(path.read_text())
    raw["model"]["gru_hiden"] = 3
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(SurgeError, match="gru_hiden"):
        load_config(path)


def test_lambda_local_must_be_positive(tmp_path):
    path = write_config(tmp_path)
    raw = yaml.safe_load(path.read_text())
    raw["loss"] = {"lambda_local": 0.0}
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(SurgeError, match="lambda_local"):
        load_config(path)


def test_paths_resolve_against_config_dir(cfg, tmp_path):
    assert cfg.runs_root == (tmp_path / "runs").resolve()


def test_smoke_override_and_sha(cfg):
    smoke = apply_overrides(cfg, smoke=True)
    assert smoke.study_id == "test-smoke" and smoke.train.epochs == 2
    assert smoke.train.limit_batches == cfg.train.smoke_batches
    assert config_sha256(apply_overrides(cfg, epochs=99)) == config_sha256(cfg)
    assert config_sha256(smoke) != config_sha256(cfg)


def test_controller_policy_does_not_change_training_identity(cfg):
    changed = cfg.model_copy(deep=True)
    changed.controller.pressure_gain = 0.2
    assert config_sha256(changed) == config_sha256(cfg)


def test_disabled_tracker_is_noop(tmp_path):
    with Tracker(False, "x", tmp_path / "t", "run") as tr:
        tr.log_params({"a": 1})
        tr.log_metrics({"m": 1.0}, step=0)
    assert not (tmp_path / "t").exists()


def test_cli_missing_config_exits_1(tmp_path, capsys):
    assert main(["select", "--config", str(tmp_path / "nope.yaml")]) == 1
    assert "CONFIG" in capsys.readouterr().err
