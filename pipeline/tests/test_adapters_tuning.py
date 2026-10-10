import json

import pytest
import yaml

from surge_ml.config import config_sha256, load_config
from surge_ml.errors import SurgeError
from surge_ml.features import VARIANTS
from surge_ml.models.registry import ADAPTERS
from surge_ml.orchestration.runner import study_dir
from surge_ml.orchestration.sweep import parse_grid, sweep, with_point
from conftest import write_config


def _with(tmp_path, **extra):
    path = write_config(tmp_path)
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    path.write_text(yaml.safe_dump({**d, **extra}), encoding="utf-8")
    return load_config(path)


def test_every_variant_has_adapter():
    assert {v.family for v in VARIANTS.values()} <= set(ADAPTERS)


def test_for_variant_merges_only_that_variant(tmp_path):
    cfg = _with(tmp_path, overrides={"gru_gatv2_40": {"model": {"gru_hidden": 12}, "train": {"lr": 5e-4}}})
    assert cfg.for_variant("gru_gatv2_40").model.gru_hidden == 12 and cfg.for_variant("gru_gatv2_40").train.lr == 5e-4
    assert cfg.for_variant("gru_local37").model.gru_hidden == cfg.model.gru_hidden == 8
    assert cfg.for_variant("gru_gatv2_40").overrides == {}


@pytest.mark.parametrize("overrides", [{"gru_gatv2_40": {"model": {"gru_hiden": 12}}},  # typo in field
                                       {"gru_gatv2_40": {"data": {"dataset_id": "y"}}},  # section not tunable
                                       {"graph41": {"model": {"gru_hidden": 12}}}])  # unknown variant
def test_bad_overrides_are_rejected(tmp_path, overrides):
    with pytest.raises(SurgeError, match="CONFIG|overrides"):
        _with(tmp_path, overrides=overrides)


def test_sha_is_isolated_per_variant(tmp_path):
    base = _with(tmp_path)
    tuned = _with(tmp_path, overrides={"gru_gatv2_40": {"model": {"gru_hidden": 12}}})
    lgbm = _with(tmp_path, lgbm={"num_leaves": 7})
    sha = lambda c, v: config_sha256(c, v)  # noqa: E731
    assert sha(tuned, "gru_gatv2_40") != sha(base, "gru_gatv2_40")
    assert sha(tuned, "gru_local37") == sha(base, "gru_local37") and sha(tuned, "lgbm37") == sha(base, "lgbm37")
    assert sha(lgbm, "lgbm37") != sha(base, "lgbm37")
    assert sha(lgbm, "gru_gatv2_40") == sha(base, "gru_gatv2_40") and sha(lgbm, "persistence") == sha(base, "persistence")


def test_parse_grid_types_and_errors(cfg):
    assert parse_grid(["model.gru_hidden=4,8", "train.lr=1e-3"]) == {"model.gru_hidden": [4, 8], "train.lr": [0.001]}
    with pytest.raises(SurgeError):
        parse_grid(["data.dataset_id=a"])
    with pytest.raises(SurgeError, match="sweep point"):
        with_point(cfg, "gru_gatv2_40", {"model.gru_hiden": 4})


def test_sweep_ranks_points_without_touching_study(cfg, data, monkeypatch):
    monkeypatch.setattr("surge_ml.orchestration.sweep.run_prepare", lambda c: None)
    monkeypatch.setattr("surge_ml.orchestration.sweep.DerivedData.load", lambda p, *a: data)
    out = sweep(cfg, "lgbm37", parse_grid(["lgbm.num_leaves=3,15"]), [1])
    assert sorted(p["point"]["lgbm.num_leaves"] for p in out["points"]) == [3, 15]
    assert out["points"][0]["mae_q_mean"] <= out["points"][1]["mae_q_mean"]
    root = study_dir(cfg)
    assert not (root / "lgbm37").exists()
    saved = json.loads((root / "_sweep" / "lgbm37" / "sweep.json").read_text(encoding="utf-8"))
    assert saved["points"][0]["override"]["lgbm"]["num_leaves"] in (3, 15)
    assert "overrides:" in (root / "_sweep" / "lgbm37" / "sweep.md").read_text(encoding="utf-8")
    again = sweep(cfg, "lgbm37", parse_grid(["lgbm.num_leaves=3,15"]), [1])  # finished points are reused
    assert [p["mae_q"] for p in again["points"]] == [p["mae_q"] for p in out["points"]]


def _current(tmp_path, dataset_id="ds_new"):
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "CURRENT.json").write_text(json.dumps({"dataset_id": dataset_id, "path": "data/ds"}))
    d = yaml.safe_load(write_config(tmp_path).read_text(encoding="utf-8"))
    d["data"] = {"current": "data/CURRENT.json", "derived_root": "derived", "dataset_id": "ds_new"}
    path = tmp_path / "train.yaml"
    path.write_text(yaml.safe_dump(d), encoding="utf-8")
    return path


def test_current_pointer_resolves_source_root(tmp_path):
    cfg = load_config(_current(tmp_path))
    assert cfg.data.source_root == (tmp_path / "data" / "ds").resolve()
    assert config_sha256(cfg, "gru_gatv2_40") and cfg.for_variant("gru_gatv2_40").data.source_root == cfg.data.source_root


def test_current_pointer_must_match_pinned_dataset(tmp_path):
    with pytest.raises(SurgeError, match="points to 'ds_other'"):
        load_config(_current(tmp_path, dataset_id="ds_other"))
