"""LightGBM đối chứng: cùng cửa sổ data.window snapshot như GRU, làm phẳng theo hex, thêm hex id; dự đoán phần dư y - b."""

from pathlib import Path

import lightgbm as lgb
import numpy as np

from surge_ml.config import LgbmConfig
from surge_ml.data.dataset import DerivedData
from surge_ml.features import COLUMNS, Variant

FIXED = {"objective": "regression_l2", "subsample_freq": 1, "verbose": -1}
ROUNDS = ("n_estimators", "early_stopping", "smoke_estimators")
MODEL_FILE = "model.txt"


def design(data: DerivedData, cols: list[int], ks: np.ndarray) -> np.ndarray:
    """Ma trận [K * N, W * len(cols) + 1], xếp theo k, khớp y[ks].reshape(-1)."""
    x = data.x[ks[:, None] + np.arange(1 - data.window, 1)][..., cols]  # [K, W, N, C]
    k, w, n, c = x.shape
    flat = x.transpose(0, 2, 1, 3).reshape(k * n, w * c)
    hex_id = np.tile(np.arange(n, dtype=np.float32), k)[:, None]
    return np.hstack([flat, hex_id])


def _rows(data: DerivedData, cols: list[int], ks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    X = design(data, cols, ks)
    r = (data.y[ks] - data.b[ks]).reshape(-1)
    ok = np.isfinite(r)
    return X[ok], r[ok]


def fit(data: DerivedData, variant: Variant, train_ks: np.ndarray, val_ks: np.ndarray, seed: int,
        out: Path, params: LgbmConfig, smoke: bool = False) -> lgb.Booster:
    cols = COLUMNS[variant.columns]
    X_tr, r_tr = _rows(data, cols, train_ks)
    X_va, r_va = _rows(data, cols, val_ks)
    cat = [X_tr.shape[1] - 1]  # hex id
    train_set = lgb.Dataset(X_tr, r_tr, categorical_feature=cat, free_raw_data=True)
    val_set = lgb.Dataset(X_va, r_va, categorical_feature=cat, reference=train_set)
    booster = lgb.train({**FIXED, **params.model_dump(exclude=set(ROUNDS)), "seed": seed}, train_set,
                        num_boost_round=params.smoke_estimators if smoke else params.n_estimators,
                        valid_sets=[val_set], callbacks=[lgb.early_stopping(params.early_stopping, verbose=False)])
    booster.save_model(str(out / MODEL_FILE), num_iteration=booster.best_iteration)
    return booster


def predict(booster: lgb.Booster, data: DerivedData, variant: Variant, ks: np.ndarray) -> dict[str, np.ndarray]:
    X = design(data, COLUMNS[variant.columns], ks)
    resid = booster.predict(X, num_iteration=booster.best_iteration or None).reshape(len(ks), data.n_nodes)
    return {"local": (data.b[ks] + resid).astype(np.float32)}


def load(path: Path) -> lgb.Booster:
    return lgb.Booster(model_file=str(path / MODEL_FILE))
