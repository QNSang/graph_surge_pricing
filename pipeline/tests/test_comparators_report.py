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
                "gru_gatv2_40": ("network", "gnn")}
    assert {n: (v.group, v.kind) for n, v in VARIANTS.items()} == expected
    assert [n for n, v in VARIANTS.items() if v.trainable] == ["gru_gatv2_40"]


def test_seasonal_naive_uses_yesterday_and_falls_back(data):
    ks = data.candidates("val")[:5]
    pred = seasonal_naive(data, ks)["local"]
    np.testing.assert_array_equal(pred, data.y[ks - SEASON])
    y = data.y.copy()
    y[ks[0] - SEASON, 0] = np.nan
    patched = type(data)(**{**data.__dict__, "y": y})
    assert seasonal_naive(patched, ks)["local"][0, 0] == data.b[ks[0], 0]


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


ERRORS = {"persistence": 1.0, "seasonal_naive": 0.8, "gru_gatv2_40": 0.3}


def test_report_picks_representatives_and_decides(cfg):
    for variant, err in ERRORS.items():
        for seed in (0, 1, 2):
            _write(cfg, variant, seed, err)
    rep = report(cfg)
    assert rep["representatives"] == {"baseline": "seasonal_naive", "network": "gru_gatv2_40"}
    c = rep["comparisons"]["gnn_vs_baseline"]
    assert c["wins"] == 3 and c["ci95"][1] < 0 and c["decision"] == "challenger wins"
    assert rep["recommendation"]["model"] == "gru_gatv2_40"
    assert "**gru_gatv2_40**" in (trial_dir(cfg, "x", 0).parents[1] / "eval_report.md").read_text(encoding="utf-8")


def test_report_keeps_baseline_when_gnn_not_clearly_better(cfg):
    for variant, err in {**ERRORS, "gru_gatv2_40": 0.85}.items():
        for seed in (0, 1, 2):
            _write(cfg, variant, seed, err)
    rep = report(cfg)
    assert rep["comparisons"]["gnn_vs_baseline"]["decision"] == "keep reference"
    assert rep["recommendation"]["model"] == "seasonal_naive"


def test_report_with_one_seed_is_not_conclusive(cfg):
    for variant, err in ERRORS.items():
        _write(cfg, variant, 0, err)
    rep = report(cfg)
    assert rep["comparisons"]["gnn_vs_baseline"]["decision"] == "not enough seeds"
    assert rep["recommendation"]["model"] == "seasonal_naive"
