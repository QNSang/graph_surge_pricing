"""Target log-ratio và persistence bypass. Chỉ numpy."""

import numpy as np

from surge_ml.features import IDX_DEMAND, IDX_EFFECTIVE, IDX_IDLE


def log_ratio(demand: np.ndarray, supply: np.ndarray) -> np.ndarray:
    return np.log((demand.astype(np.float64) + 1.0) / (supply.astype(np.float64) + 1.0))


def build_targets(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """x [T, N, 40] thô -> y, b, b32 mỗi cái float32 [T, N]; y[k] = log q[k+1], y[T-1] là NaN."""
    b = log_ratio(x[..., IDX_DEMAND], x[..., IDX_EFFECTIVE])
    b32 = log_ratio(x[..., IDX_DEMAND], x[..., IDX_IDLE])
    y = np.full_like(b, np.nan)
    y[:-1] = b[1:]
    return y.astype(np.float32), b.astype(np.float32), b32.astype(np.float32)


def to_ratio(log_q: np.ndarray) -> np.ndarray:
    """Nghịch đảo của biến đổi target; không dùng expm1 vì target là log q, không phải log1p."""
    return np.exp(log_q)
