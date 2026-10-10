"""Metric dự báo. Mảng [K, N] ở không gian log; q = exp(.)."""

import numpy as np
from scipy.stats import rankdata

from surge_ml.data.target import to_ratio


def pair_accuracy(pred: np.ndarray, y: np.ndarray, mask: np.ndarray) -> float | None:
    """Tỉ lệ cặp hex cùng thời điểm được xếp đúng thứ tự; bỏ qua cặp target bằng nhau."""
    dy = y[:, :, None] - y[:, None, :]
    dp = pred[:, :, None] - pred[:, None, :]
    upper = np.triu(np.ones(y.shape[1], bool), 1)
    valid = mask[:, :, None] & mask[:, None, :] & upper & (dy != 0)
    n = int(valid.sum())
    return float((np.sign(dy) == np.sign(dp))[valid].mean()) if n else None


def mean_spearman(pred: np.ndarray, y: np.ndarray, mask: np.ndarray) -> float | None:
    """Spearman trung bình trên các thời điểm quan sát đủ và có hạng không hằng."""
    rows = mask.all(1)
    if not rows.any():
        return None
    rp, ry = rankdata(pred[rows], axis=1), rankdata(y[rows], axis=1)
    rp -= rp.mean(1, keepdims=True)
    ry -= ry.mean(1, keepdims=True)
    denom = np.sqrt((rp * rp).sum(1) * (ry * ry).sum(1))
    ok = denom > 0
    return float(((rp * ry).sum(1)[ok] / denom[ok]).mean()) if ok.any() else None


def head_metrics(pred: np.ndarray, y: np.ndarray, mask: np.ndarray, beta: float) -> dict[str, float | None]:
    p, t = pred[mask].astype(np.float64), y[mask].astype(np.float64)
    if len(t) == 0:
        return {}
    e_log = p - t
    e_q = to_ratio(p) - to_ratio(t)
    a = np.abs(e_log)
    return {
        "mae_q": float(np.abs(e_q).mean()),
        "rmse_q": float(np.sqrt((e_q * e_q).mean())),
        "bias_q": float(e_q.mean()),
        "mae_log": float(a.mean()),
        "smoothl1_log": float(np.where(a < beta, 0.5 * a * a / beta, a - 0.5 * beta).mean()),
        "bias_log": float(e_log.mean()),
        "pair_acc": pair_accuracy(pred, y, mask),
        "spearman": mean_spearman(pred, y, mask),
        "n": int(len(t)),
    }


def evaluate_predictions(preds: dict[str, np.ndarray], y: np.ndarray, b: np.ndarray, beta: float) -> dict:
    mask = np.isfinite(y) & np.isfinite(b)
    out: dict = {head: head_metrics(p, y, mask, beta) for head, p in preds.items()}
    if "local" in preds and "graph" in preds:
        q = to_ratio(y[mask].astype(np.float64))
        gain = np.abs(to_ratio(preds["local"][mask].astype(np.float64)) - q) \
            - np.abs(to_ratio(preds["graph"][mask].astype(np.float64)) - q)
        out["paired_gain_q"] = float(gain.mean())
    return out


def flatten(metrics: dict, prefix: str) -> dict[str, float]:
    """Làm phẳng dict metric thành khoá dạng "val/local/mae_q"."""
    out = {}
    for key, value in metrics.items():
        if isinstance(value, dict):
            out.update({f"{prefix}/{key}/{m}": v for m, v in value.items() if v is not None and m != "n"})
        elif value is not None:
            out[f"{prefix}/{key}"] = value
    return out
