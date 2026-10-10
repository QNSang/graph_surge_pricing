"""Baseline không huấn luyện. Persistence: y_hat = b. Seasonal-naive: y_hat = target cùng giờ hôm qua, thiếu thì dùng b."""

import numpy as np

from surge_ml.data.dataset import DerivedData

SEASON = 288  # snapshots per day at 5 min


def persistence(data: DerivedData, ks: np.ndarray) -> dict[str, np.ndarray]:
    return {"local": data.b[ks]}


def seasonal_naive(data: DerivedData, ks: np.ndarray) -> dict[str, np.ndarray]:
    """y[k - 288] đã quan sát được tại cutoff k nên không dùng dữ liệu tương lai."""
    if (ks < SEASON).any():
        raise ValueError(f"seasonal_naive needs k >= {SEASON}")
    pred = data.y[ks - SEASON]
    return {"local": np.where(np.isfinite(pred), pred, data.b[ks])}


BASELINES = {"persistence": persistence, "seasonal": seasonal_naive}
