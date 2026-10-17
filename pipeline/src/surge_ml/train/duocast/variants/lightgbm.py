from __future__ import annotations
from pathlib import Path
import numpy as np
from surge_ml.train.duocast._types import Config
from surge_ml.train.duocast._constant import TARGETS
from surge_ml.datasets.duocast import Panel

def tabular_features(panel, cutoffs, cfg, network=False):
    if network:
        raise ValueError('Only the local LightGBM baseline belongs to this benchmark')
    ks = np.asarray(cutoffs, dtype=np.int64)
    history, n = cfg.data.history, panel.n_nodes
    indices = ks[:, None] + np.arange(-history + 1, 1)
    matrix = panel.dynamic[indices].transpose(0, 2, 1, 3).reshape(len(ks) * n, -1)
    names = [f'lag{lag}_{name}' for lag in range(history - 1, -1, -1) for name in cfg.data.dynamic_features]
    return matrix, names

def fit_lightgbm(panel: Panel, splits: dict, cfg: Config, variant: str, seed: int, folder: Path):
    try:
        import lightgbm as lgb
    except ImportError as exc:
        raise ValueError("LightGBM baselines require the baselines extra: uv sync --project pipeline --extra baselines") from exc
    network = False
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
    x, _ = tabular_features(panel, cutoffs, cfg, False)
    log_pred = np.stack([m.predict(x) for m in boosters], axis=-1)
    with np.errstate(over="ignore"):
        pred = np.expm1(np.maximum(log_pred, 0))
    if not np.isfinite(pred).all():
        raise FloatingPointError("Nonfinite LightGBM forecast")
    return pred.reshape(len(cutoffs), panel.n_nodes, 2)
