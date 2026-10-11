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


def collate_temporal_edges(
    data: DerivedData, ks: np.ndarray, relations: tuple[str, ...]
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Align observed edge histories to edges available at each input cutoff.

    Current edges define sparse graph topology. For each selected (src,dst,
    relation) we lookup only snapshots k-W+1..k; missing earlier OD relations
    carry zero-padded z-scored features AND an explicit observation mask.
    Relation key disambiguates adjacent and OD edges between the same nodes.
    Synthetic self-loops have relation=2 and no observed edge history.
    No future snapshot or oracle table is accessed.
    """
    index, attr = collate_edges(data, ks, relations)
    n, window = data.n_nodes, data.window
    observed_edges = index.shape[1] - len(ks) * n
    edge_relation = np.full(index.shape[1], 2, dtype=np.int64)
    history = np.zeros((index.shape[1], window, EDGE_DIM - 1), dtype=np.float32)
    presence = np.zeros((index.shape[1], window), dtype=np.bool_)
    keep = data.keep_mask(relations)
    offset = 0

    for k in ks:
        k = int(k)
        if k - window + 1 < 0:
            raise ValueError("Temporal edge history would read before the dataset start")
        lo, hi = int(data.edge_ptr[k]), int(data.edge_ptr[k + 1])
        current = np.arange(lo, hi, dtype=np.int64)[keep[lo:hi]]
        size = len(current)
        if size == 0:
            continue
        src = data.edge_src[current]
        dst = data.edge_dst[current]
        typ = np.where(data.edge_is_adj[current], 0, 1).astype(np.int64)
        edge_relation[offset:offset + size] = typ
        keys = (src * n + dst) * 2 + typ

        for t in range(window):
            step = k - window + 1 + t
            start, end = int(data.edge_ptr[step]), int(data.edge_ptr[step + 1])
            hist_type = np.where(data.edge_is_adj[start:end], 0, 1)
            hist_keys = ((data.edge_src[start:end] * n
                          + data.edge_dst[start:end]) * 2 + hist_type)
            order = np.argsort(hist_keys, kind="stable")
            sorted_keys = hist_keys[order]
            pos = np.searchsorted(sorted_keys, keys)
            eligible = np.flatnonzero(pos < len(sorted_keys))
            if not len(eligible):
                continue
            eligible = eligible[sorted_keys[pos[eligible]] == keys[eligible]]
            if len(eligible):
                history[offset + eligible, t] = data.edge_attr[start + order[pos[eligible]]]
                presence[offset + eligible, t] = True
        offset += size

    if offset != observed_edges:
        raise AssertionError("Temporal edge order differs from current graph collation")
    if observed_edges and not bool(presence[:observed_edges, -1].all()):
        raise AssertionError("Every selected cutoff edge must exist at its own timestamp")
    return index, attr, history, presence, edge_relation


def make_batch(data: DerivedData, ks: np.ndarray, variant: Variant, device: torch.device | str = "cpu") -> dict:
    x = data.x[ks[:, None] + np.arange(1 - data.window, 1)]  # [B, W, N, 40]
    bypass = data.b32 if variant.bypass == "b32" else data.b
    out = {"x_local": x[..., COLUMNS[variant.columns]], "y": data.y[ks], "b": bypass[ks]}
    if variant.graph:
        out["x_neighbor"] = x[..., NEIGHBOR3]
        if variant.family == "flow_gru":
            (out["edge_index"], out["edge_attr"], out["edge_history"],
             out["edge_history_mask"], out["edge_relation"]) = collate_temporal_edges(
                 data, ks, variant.relations)
        else:
            out["edge_index"], out["edge_attr"] = collate_edges(data, ks, variant.relations)
    return {k: torch.from_numpy(np.ascontiguousarray(v)).to(device) for k, v in out.items()}
