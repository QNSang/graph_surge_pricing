"""Count-scale diagnostics; thresholds are fixed before test evaluation."""
from __future__ import annotations

import numpy as np

from .config import EvalConfig, TrainConfig


def point_metrics(pred, truth, evaluation: EvalConfig, train: TrainConfig) -> dict:
    pred = np.asarray(pred, dtype=np.float64).reshape(-1, 2)
    truth = np.asarray(truth, dtype=np.float64).reshape(-1, 2)
    if pred.shape != truth.shape:
        raise ValueError("Prediction and target shapes differ")
    if len(pred) == 0:
        return {"rows": 0}
    if not np.isfinite(pred).all() or not np.isfinite(truth).all() or (pred < 0).any() or (truth < 0).any():
        raise ValueError("Metrics require finite nonnegative demand/supply counts")
    error = pred - truth
    absolute = np.abs(error)
    out = {"rows": len(pred)}
    for j, name in enumerate(("demand", "supply")):
        total = truth[:, j].sum()
        out[f"{name}_mae"] = float(absolute[:, j].mean())
        out[f"{name}_rmse"] = float(np.sqrt(np.mean(error[:, j] ** 2)))
        out[f"{name}_wape"] = float(absolute[:, j].sum() / total) if total > 0 else None
    pred_ratio = pred[:, 0] / (pred[:, 1] + 1.0)
    true_ratio = truth[:, 0] / (truth[:, 1] + 1.0)
    guess = pred_ratio > evaluation.shortage_threshold
    actual = true_ratio > evaluation.shortage_threshold
    tp = int(np.sum(guess & actual))
    fp, fn = int(np.sum(guess & ~actual)), int(np.sum(~guess & actual))
    out.update(ds_proxy_mae=float(np.abs(pred_ratio - true_ratio).mean()),
               shortage_precision=tp / (tp + fp) if tp + fp else None,
               shortage_recall=tp / (tp + fn) if tp + fn else None,
               shortage_f1=2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
               shortage_prevalence=float(actual.mean()), shortage_tp=tp, shortage_fp=fp,
               shortage_fn=fn, shortage_threshold=evaluation.shortage_threshold)
    residual = np.abs(np.log1p(pred) - np.log1p(truth))
    delta = train.huber_delta
    losses = np.where(residual <= delta, 0.5 * residual ** 2, delta * (residual - 0.5 * delta)).mean(axis=0)
    out["loss_demand"] = float(losses[0])
    out["loss_supply"] = float(losses[1])
    out["loss_log_huber"] = float(losses.mean())
    return out


def evaluate(pred, truth, panel, cutoffs, evaluation: EvalConfig, train: TrainConfig,
             high_demand_cut: float) -> dict:
    pred, truth = np.asarray(pred), np.asarray(truth)
    if pred.shape != truth.shape or pred.shape != (len(cutoffs), panel.n_nodes, 2):
        raise ValueError("Evaluation expects [cutoffs,nodes,2]")
    score = lambda p, y: point_metrics(p, y, evaluation, train)
    ratio = truth[..., 0] / (truth[..., 1] + 1.0)
    masks = {"high_demand": truth[..., 0] >= high_demand_cut,
             "low_supply": truth[..., 1] <= evaluation.low_supply_threshold,
             "zero_supply": truth[..., 1] == 0,
             "high_pressure": ratio > evaluation.shortage_threshold}
    hours = panel.timestamps[np.asarray(cutoffs) + 1].hour.to_numpy()
    return {"overall": score(pred, truth),
            "segments": {name: score(pred[mask], truth[mask]) for name, mask in masks.items()},
            "by_hex": {h: score(pred[:, i], truth[:, i]) for i, h in enumerate(panel.hex_ids)},
            "by_hour": {str(int(hour)): score(pred[hours == hour], truth[hours == hour]) for hour in np.unique(hours)},
            "thresholds": {"high_demand": float(high_demand_cut),
                           "high_demand_source": "training target quantile",
                           "low_supply": evaluation.low_supply_threshold,
                           "shortage": evaluation.shortage_threshold},
            "ds_proxy_definition": "D / (idle_supply + 1); diagnostic only, not a pricing rule"}
