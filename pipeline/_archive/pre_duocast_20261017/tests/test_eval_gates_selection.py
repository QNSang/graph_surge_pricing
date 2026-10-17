import json

import numpy as np
import pytest

from surge_ml.config import config_sha256
from surge_ml.errors import SurgeError
from surge_ml.evaluation.metrics import evaluate_predictions, flatten, mean_spearman, pair_accuracy
from surge_ml.evaluation.selection import select
from surge_ml.orchestration.runner import trial_dir


def test_metrics_use_exp_inverse():
    y = np.log(np.array([[1.0, 2.0, 4.0]]))
    pred = np.log(np.array([[2.0, 2.0, 2.0]]))
    m = evaluate_predictions({"local": pred, "graph": y.copy()}, y, np.zeros_like(y), beta=1.0)
    assert m["local"]["mae_q"] == pytest.approx((1 + 0 + 2) / 3)
    assert m["local"]["bias_q"] == pytest.approx((1 + 0 - 2) / 3)
    assert m["graph"]["mae_q"] == pytest.approx(0.0)
    assert m["paired_gain_q"] == pytest.approx(1.0)
    assert flatten(m, "val")["val/local/mae_q"] == m["local"]["mae_q"]


def test_rank_metrics():
    y = np.array([[1.0, 2.0, 3.0], [3.0, 2.0, 1.0]])
    mask = np.ones_like(y, bool)
    assert pair_accuracy(y * 2, y, mask) == 1.0
    assert pair_accuracy(-y, y, mask) == 0.0
    assert mean_spearman(y, y, mask) == pytest.approx(1.0)


def _write_trials(cfg, rows, sha=None):
    for variant, head, scores in rows:
        for seed, s in enumerate(scores):
            path = trial_dir(cfg, variant, seed) / "trial_result.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"variant": variant, "seed": seed, "primary_head": head,
                                        "config_sha256": sha or config_sha256(cfg, variant), "val": {head: {"mae_q": s}}}))


def test_select_ranks_by_mean_val_primary(cfg):
    cfg.seeds, cfg.variants = [0, 1], ["gru_gatv2_40", "persistence"]
    _write_trials(cfg, [("gru_gatv2_40", "graph", [0.2, 0.4]), ("persistence", "local", [0.35, 0.35])])
    sel = select(cfg)
    assert sel["selected"] == "gru_gatv2_40" and sel["variants"]["gru_gatv2_40"]["mean_mae_q"] == pytest.approx(0.3)


def test_select_rejects_incomplete_study(cfg):
    cfg.seeds, cfg.variants = [0, 1], ["gru_gatv2_40", "persistence"]
    _write_trials(cfg, [("gru_gatv2_40", "graph", [0.2, 0.4])])
    with pytest.raises(SurgeError, match="missing"):
        select(cfg)


def test_select_rejects_stale_trials(cfg):
    cfg.seeds, cfg.variants = [0], ["gru_gatv2_40"]
    _write_trials(cfg, [("gru_gatv2_40", "graph", [0.2])], sha="old")
    with pytest.raises(SurgeError, match="different config"):
        select(cfg)


def test_select_without_trials_fails(cfg):
    with pytest.raises(SurgeError):
        select(cfg)
