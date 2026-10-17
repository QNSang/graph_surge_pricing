"""Naive and optional LightGBM baselines on the same causal windows/targets."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .config import Config, TARGETS
from .data import Panel


def naive_predictions(panel: Panel, cutoffs, variant: str, period: int):
    cutoffs = np.asarray(cutoffs, dtype=np.int64)
    if variant == "persistence":
        return panel.target[cutoffs].astype(np.float64), {"seasonal_fallback_cutoffs": 0}
    if variant != "seasonal_naive":
        raise ValueError(f"Not a naive baseline: {variant}")
    historic = cutoffs + 1 - period
    # Short startup histories use explicitly reported persistence fallback.
    valid = historic >= 0
    pred = panel.target[cutoffs].copy()
    pred[valid] = panel.target[historic[valid]]
    return pred.astype(np.float64), {"seasonal_fallback_cutoffs": int((~valid).sum()),
                                   "seasonal_period_steps": period}


def tabular_features(panel: Panel, cutoffs, cfg: Config, network: bool):
    ks = np.asarray(cutoffs, dtype=np.int64)
    n, history = panel.n_nodes, cfg.data.history
    indices = ks[:, None] + np.arange(-history + 1, 1)
    windows = panel.dynamic[indices].transpose(0, 2, 1, 3).reshape(len(ks), n, -1)
    blocks = [windows]
    names = [f"lag{lag}_{name}" for lag in range(history - 1, -1, -1)
             for name in cfg.data.dynamic_features]
    if network:
        blocks.append(np.broadcast_to(panel.geo[None], (len(ks), *panel.geo.shape)))
        names.extend(f"geo_{name}" for name in cfg.data.geo_features)
        adjacency = np.zeros((n, n), dtype=np.float64)
        adjacency[panel.spatial_index[1], panel.spatial_index[0]] = 1.0
        degree = adjacency.sum(axis=1)
        normalized = adjacency / np.maximum(degree[:, None], 1)
        current = panel.target[ks]
        blocks.append(np.einsum("ij,bjf->bif", normalized, current))
        names.extend(["neighbor_demand", "neighbor_idle_supply"])
        # Edge-attribute sums/means are observed at the cutoff, not future arrivals.
        width = len(cfg.data.mobility_features)
        aggregates = np.zeros((len(ks), n, 2 * width + 2), dtype=np.float32)
        for b, k in enumerate(ks):
            low, high = panel.mobility_ptr[k:k + 2]
            src, dst = panel.mobility_index[:, low:high]
            attr = panel.mobility_attr[low:high]
            np.add.at(aggregates[b, :, :width], dst, attr)
            np.add.at(aggregates[b, :, width:2 * width], src, attr)
            np.add.at(aggregates[b, :, -2], dst, 1)
            np.add.at(aggregates[b, :, -1], src, 1)
        blocks.append(aggregates)
        names.extend([f"od_in_sum_{name}" for name in cfg.data.mobility_features])
        names.extend([f"od_out_sum_{name}" for name in cfg.data.mobility_features])
        names.extend(["od_in_degree", "od_out_degree"])
        if cfg.data.spatial_features:
            road = np.zeros((n, len(cfg.data.spatial_features)), dtype=np.float32)
            np.add.at(road, panel.spatial_index[1], panel.spatial_attr)
            road /= np.maximum(degree[:, None], 1)
            blocks.append(np.broadcast_to(road[None], (len(ks), *road.shape)))
            names.extend([f"spatial_mean_{name}" for name in cfg.data.spatial_features])
    matrix = np.concatenate(blocks, axis=-1).reshape(len(ks) * n, -1)
    return matrix, names


def fit_lightgbm(panel: Panel, splits: dict, cfg: Config, variant: str, seed: int, folder: Path):
    try:
        import lightgbm as lgb
    except ImportError as exc:
        raise ValueError("LightGBM baselines require the geomobinet optional dependencies") from exc
    network = variant == "lgbm_network"
    x, names = tabular_features(panel, splits["train"], cfg, network)
    val_x, _ = tabular_features(panel, splits["val"], cfg, network)
    truth = np.log1p(panel.target[splits["train"] + 1].reshape(-1, 2))
    val_truth = np.log1p(panel.target[splits["val"] + 1].reshape(-1, 2))
    params = {"objective": "regression_l1", "metric": "l1", "learning_rate": 0.05,
              "num_leaves": 31, "min_data_in_leaf": 20, "lambda_l2": 1.0,
              "num_threads": cfg.train.num_threads, "seed": seed,
              "deterministic": True, "force_col_wise": True, "verbosity": -1}
    boosters = []
    for j, target in enumerate(TARGETS):
        model = lgb.train(params, lgb.Dataset(x, label=truth[:, j], feature_name=names),
                          num_boost_round=cfg.train.lgbm_rounds,
                          valid_sets=[lgb.Dataset(val_x, label=val_truth[:, j])],
                          callbacks=[lgb.early_stopping(min(30, cfg.train.lgbm_rounds), verbose=False)])
        model.save_model(str(folder / f"{target}.txt"), num_iteration=model.best_iteration)
        boosters.append(model)
    return predict_lightgbm(panel, splits["val"], cfg, variant, folder, boosters), {
        "feature_names": names, "best_iterations": [int(m.best_iteration) for m in boosters]}


def predict_lightgbm(panel, cutoffs, cfg, variant, folder, boosters=None):
    if boosters is None:
        try:
            import lightgbm as lgb
        except ImportError as exc:
            raise ValueError("LightGBM is not installed") from exc
        boosters = [lgb.Booster(model_file=str(folder / f"{name}.txt")) for name in TARGETS]
    x, _ = tabular_features(panel, cutoffs, cfg, variant == "lgbm_network")
    log_pred = np.stack([m.predict(x) for m in boosters], axis=-1)
    with np.errstate(over="ignore"):
        pred = np.expm1(np.maximum(log_pred, 0))
    if not np.isfinite(pred).all():
        raise FloatingPointError("Nonfinite LightGBM forecast")
    return pred.reshape(len(cutoffs), panel.n_nodes, 2)
