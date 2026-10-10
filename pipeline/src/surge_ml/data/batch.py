"""Ghép batch: cửa sổ data.window snapshot, cạnh tại cutoff k, offset i + j*N, self-loop tổng hợp."""

import numpy as np
import torch

from surge_ml.data.dataset import DerivedData
from surge_ml.features import COLUMNS, EDGE_DIM, NEIGHBOR3, Variant


def collate_edges(data: DerivedData, ks: np.ndarray, relations: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
    n = data.n_nodes
    keep = data.keep_mask(relations)
    srcs, dsts, attrs = [], [], []
    for j, k in enumerate(ks):
        lo, hi = data.edge_ptr[k], data.edge_ptr[k + 1]
        sel = keep[lo:hi]
        srcs.append(data.edge_src[lo:hi][sel] + j * n)
        dsts.append(data.edge_dst[lo:hi][sel] + j * n)
        attrs.append(data.edge_attr[lo:hi][sel])
    loops = np.arange(len(ks) * n, dtype=np.int64)
    observed = np.concatenate(attrs)
    attr = np.zeros((len(observed) + len(loops), EDGE_DIM), np.float32)
    attr[: len(observed), : EDGE_DIM - 1] = observed
    attr[len(observed):, EDGE_DIM - 1] = 1.0  # is_self
    edge_index = np.stack([np.concatenate([*srcs, loops]), np.concatenate([*dsts, loops])])
    return edge_index, attr


def make_batch(data: DerivedData, ks: np.ndarray, variant: Variant, device: torch.device | str = "cpu") -> dict:
    x = data.x[ks[:, None] + np.arange(1 - data.window, 1)]  # [B, W, N, 40]
    bypass = data.b32 if variant.bypass == "b32" else data.b
    out = {"x_local": x[..., COLUMNS[variant.columns]], "y": data.y[ks], "b": bypass[ks]}
    if variant.graph:
        out["x_neighbor"] = x[..., NEIGHBOR3]
        out["edge_index"], out["edge_attr"] = collate_edges(data, ks, variant.relations)
    return {k: torch.from_numpy(np.ascontiguousarray(v)).to(device) for k, v in out.items()}
