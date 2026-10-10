import json

import numpy as np
import pytest

from surge_ml.config import config_sha256
from surge_ml.evaluation.report import report
from surge_ml.features import VARIANTS
from surge_ml.models.baselines import SEASON, seasonal_naive
from surge_ml.orchestration.runner import run_trial, trial_dir


def test_variant_groups():
    expected = {"persistence": ("baseline", None), "seasonal_naive": ("baseline", None),
                "gru_strict32": ("local", None), "gru_local37": ("local", None), "lgbm37": ("local", None),
                "gru_pointwise40": ("network", "handcrafted"), "lgbm40": ("network", "handcrafted"),
                "gru_gatv2_40": ("network", "gnn"), "gru_gatv2_40_no_od": ("network", "gnn"),
                "gru_gatv2_40_no_adj": ("network", "gnn")}
    assert {n: (v.group, v.kind) for n, v in VARIANTS.items()} == expected
    assert [n for n, v in VARIANTS.items() if v.trainable] == [
        "gru_local37", "gru_pointwise40", "gru_strict32", "gru_gatv2_40", "gru_gatv2_40_no_od",
        "gru_gatv2_40_no_adj"]


def test_seasonal_naive_uses_yesterday_and_falls_back(data):
    ks = data.candidates("val")[:5]
    pred = seasonal_naive(data, ks)["local"]
    np.testing.assert_array_equal(pred, data.y[ks - SEASON])
    y = data.y.copy()
    y[ks[0] - SEASON, 0] = np.nan
    patched = type(data)(**{**data.__dict__, "y": y})
    assert seasonal_naive(patched, ks)["local"][0, 0] == data.b[ks[0], 0]


def test_lgbm_trial_writes_model_preds_and_time(cfg, data):
    result = run_trial(cfg, data, VARIANTS["lgbm37"], seed=1)
    out = trial_dir(cfg, "lgbm37", 1)
    assert (out / "model.txt").is_file() and result["train_seconds"] > 0 and result["n_trees"] > 0
    z = np.load(out / "val_preds.npz")
    assert z["pred"].shape == z["abs_err_q"].shape == (len(z["ks"]), data.n_nodes)
    assert result["val"]["local"]["mae_q"] == pytest.approx(np.nanmean(z["abs_err_q"]), rel=1e-4)


def _write(cfg, variant, seed, err, k=48, n=4):
    out = trial_dir(cfg, variant, seed)
    out.mkdir(parents=True)
    rng = np.random.default_rng(seed)
    e = err + 0.01 * rng.random((k, n))
    np.savez(out / "val_preds.npz", ks=np.arange(k), pred=np.zeros((k, n), np.float32), abs_err_q=e)
    head = VARIANTS[variant].primary_head
    (out / "trial_result.json").write_text(json.dumps({
        "variant": variant, "seed": seed, "primary_head": head, "config_sha256": config_sha256(cfg, variant),
        "n_params": 10, "train_seconds": 1.0, "val": {head: {"mae_q": float(e.mean())}}}))


ERRORS = {"persistence": 1.0, "gru_local37": 0.5, "gru_pointwise40": 0.4, "gru_gatv2_40": 0.3}


def test_report_picks_representatives_and_decides(cfg):
    for variant, err in ERRORS.items():
        for seed in (0, 1, 2):
            _write(cfg, variant, seed, err)
    rep = report(cfg)
    assert rep["representatives"] == {"baseline": "persistence", "local": "gru_local37",
                                      "network": "gru_gatv2_40", "handcrafted": "gru_pointwise40",
                                      "gnn": "gru_gatv2_40"}
    c = rep["comparisons"]
    assert c["network_vs_local"]["wins"] == 3 and c["network_vs_local"]["ci95"][1] < 0
    assert all(x["decision"] == "challenger wins" for x in c.values())
    assert rep["recommendation"]["model"] == "gru_gatv2_40"
    assert "**gru_gatv2_40**" in (trial_dir(cfg, "x", 0).parents[1] / "eval_report.md").read_text(encoding="utf-8")


def test_report_keeps_local_when_gnn_not_clearly_better(cfg):
    for variant, err in {**ERRORS, "gru_gatv2_40": 0.4}.items():
        for seed in (0, 1, 2):
            _write(cfg, variant, seed, err)
    rep = report(cfg)
    assert rep["comparisons"]["gnn_vs_handcrafted"]["decision"] == "keep reference"
    assert rep["recommendation"]["model"] == "gru_pointwise40"


def test_report_with_one_seed_is_not_conclusive(cfg):
    for variant, err in ERRORS.items():
        _write(cfg, variant, 0, err)
    rep = report(cfg)
    assert all(c["decision"] == "not enough seeds" for c in rep["comparisons"].values())
    assert rep["recommendation"]["model"] == "gru_local37"
