"""Train-only scaling and independent graph batches; inference needs no future labels."""
from __future__ import annotations

import numpy as np
import torch

from .config import DataConfig
from .data import Panel


class Scaler:
    def __init__(self, names, log_names=(), mean=None, std=None, observed=None):
        self.names = list(names)
        self.log_names = list(log_names)
        self.mean = None if mean is None else np.asarray(mean, dtype=np.float64)
        self.std = None if std is None else np.asarray(std, dtype=np.float64)
        self.observed = observed

    def initial(self, values):
        result = np.asarray(values, dtype=np.float64).copy()
        if result.shape[-1] != len(self.names):
            raise ValueError("Scaler feature dimension mismatch")
        for i, name in enumerate(self.names):
            if name in self.log_names:
                if (result[..., i] < 0).any():
                    raise ValueError(f"Negative input to log1p: {name}")
                result[..., i] = np.log1p(result[..., i])
        if np.isinf(result).any():
            raise ValueError("Infinite input to scaler")
        return result

    def fit(self, values):
        values = self.initial(values)
        if not self.names:
            self.mean, self.std, self.observed = np.zeros(0), np.ones(0), []
            return self
        flat = values.reshape(-1, len(self.names))
        valid = np.isfinite(flat)
        count = valid.sum(axis=0)
        self.mean = np.where(valid, flat, 0).sum(axis=0) / np.maximum(count, 1)
        variance = np.where(valid, (flat - self.mean) ** 2, 0).sum(axis=0) / np.maximum(count, 1)
        self.std = np.sqrt(variance)
        self.std[self.std < 1e-6] = 1.0
        self.observed = count.tolist()
        return self

    def transform(self, values):
        if self.mean is None or self.std is None or (self.std <= 0).any():
            raise ValueError("Scaler is unfitted or invalid")
        scaled = (self.initial(values) - self.mean) / self.std
        # Explicit train-mean imputation. Batcher appends a stable mask for EVERY nullable feature.
        scaled = np.where(np.isnan(scaled), 0, scaled)
        with np.errstate(over="ignore"):
            result = scaled.astype(np.float32)
        if not np.isfinite(result).all():
            raise ValueError("Nonfinite scaled features")
        return result

    def state(self):
        return {"names": self.names, "log_names": self.log_names, "mean": self.mean.tolist(),
                "std": self.std.tolist(), "observed": self.observed}


def fit_scalers(panel: Panel, train_cutoffs: np.ndarray, cfg: DataConfig) -> dict:
    first = int(train_cutoffs[0]) - cfg.history + 1
    last = int(train_cutoffs[-1])
    low, high = panel.mobility_ptr[first], panel.mobility_ptr[last + 1]
    arrays = {"dynamic": panel.dynamic[first:last + 1], "geo": panel.geo,
              "spatial": panel.spatial_attr, "mobility": panel.mobility_attr[low:high]}
    return {name: Scaler(getattr(cfg, f"{name}_features"), getattr(cfg, f"log_{name}"))
            .fit(value).state() for name, value in arrays.items()}


class Batcher:
    def __init__(self, panel: Panel, cfg: DataConfig, scalers: dict, device="cpu"):
        self.panel, self.cfg = panel, cfg
        self.device = torch.device(device)
        scaled = {}
        for name, raw in (("dynamic", panel.dynamic), ("geo", panel.geo),
                          ("spatial", panel.spatial_attr), ("mobility", panel.mobility_attr)):
            if scalers[name]["names"] != getattr(cfg, f"{name}_features"):
                raise ValueError(f"{name} feature order differs from checkpoint")
            scaled[name] = Scaler(**scalers[name]).transform(raw)
        masks = [np.isfinite(panel.dynamic[..., cfg.dynamic_features.index(c)])[..., None]
                 for c in cfg.nullable_dynamic]
        self.dynamic = np.concatenate([scaled["dynamic"], *masks], axis=-1).astype(np.float32)
        self.geo, self.spatial, self.mobility = scaled["geo"], scaled["spatial"], scaled["mobility"]

    @property
    def n_dynamic(self):
        return self.dynamic.shape[-1]

    def build(self, cutoffs, *, targets=True):
        ks = np.asarray(cutoffs, dtype=np.int64)
        p, cfg = self.panel, self.cfg
        if ks.ndim != 1 or not len(ks) or (ks < cfg.history - 1).any() or (ks >= len(p.timestamps)).any():
            raise ValueError("Invalid cutoff/history for graph batch")
        if targets and (ks + cfg.horizon >= len(p.timestamps)).any():
            raise ValueError("Training target is unavailable; use targets=False for live inference")
        b, n = len(ks), p.n_nodes
        steps = ks[:, None] + np.arange(-cfg.history + 1, 1)[None, :]
        window = self.dynamic[steps].transpose(0, 2, 1, 3).reshape(b * n, cfg.history, -1)
        sp_index = np.concatenate([p.spatial_index + j * n for j in range(b)], axis=1)
        od_indices, od_attrs = [], []
        for j, k in enumerate(ks):
            low, high = p.mobility_ptr[k:k + 2]
            od_indices.append(p.mobility_index[:, low:high] + j * n)
            od_attrs.append(self.mobility[low:high])
        arrays = {"x_dyn": window, "x_geo": np.tile(self.geo, (b, 1)),
                  "spatial_index": sp_index, "spatial_attr": np.tile(self.spatial, (b, 1)),
                  "mobility_index": np.concatenate(od_indices, axis=1),
                  "mobility_attr": np.concatenate(od_attrs, axis=0)}
        if targets:
            arrays["y"] = p.target[ks + cfg.horizon].reshape(b * n, 2)
        return {key: torch.from_numpy(np.ascontiguousarray(value)).to(self.device)
                for key, value in arrays.items()}
