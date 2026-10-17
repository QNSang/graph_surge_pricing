"""Kiểm tra hợp đồng nguồn do `prepare` chạy."""

import numpy as np

from surge_ml.errors import SurgeError
from surge_ml.features import (ANCHORS, EDGE_ANCHORS, IDX_EDGE_ADJ, IDX_EDGE_OD, N_EDGE_FEATURES,
                               N_NODE_FEATURES, SNAPSHOT_SECONDS)


def check(ok: bool, message: str) -> None:
    if not ok:
        raise SurgeError("SOURCE", message)


def check_contract(manifest: dict, contract: dict, dataset_id: str) -> None:
    check(manifest.get("dataset_id") == dataset_id,
          f"dataset_id {manifest.get('dataset_id')!r} != config {dataset_id!r}")
    nodes, edges, hexes = contract["node_features"], contract["edge_features"], contract["hex_ids"]
    check(len(nodes) == N_NODE_FEATURES, f"expected {N_NODE_FEATURES} node features, got {len(nodes)}")
    check(len(edges) == N_EDGE_FEATURES, f"expected {N_EDGE_FEATURES} edge features, got {len(edges)}")
    for i, name in ANCHORS.items():
        check(nodes[i] == name, f"node_features[{i}] is {nodes[i]!r}, expected {name!r}")
    for i, name in EDGE_ANCHORS.items():
        check(edges[i] == name, f"edge_features[{i}] is {edges[i]!r}, expected {name!r}")
    check(len(set(hexes)) == len(hexes) == manifest.get("hex_count"), "hex_ids not unique or count mismatch")


def check_grid(grid_ns: np.ndarray, n_snapshots: int) -> None:
    check(len(grid_ns) == n_snapshots, f"expected {n_snapshots} snapshots (manifest days x 288), got {len(grid_ns)}")
    check(bool(np.all(np.diff(grid_ns) == SNAPSHOT_SECONDS * 10**9)), "snapshot grid is not contiguous 5 min")


def check_nodes(x: np.ndarray, counts: np.ndarray) -> None:
    check(bool(np.all(counts == 1)), f"{int(np.sum(counts != 1))} (ts, hex) cells missing or duplicated")
    check(bool(np.isfinite(x).all()), "node features contain non-finite values")


def check_edges(attr: np.ndarray) -> None:
    check(bool(np.isfinite(attr).all()), "edge features contain non-finite values")
    flags = attr[:, IDX_EDGE_ADJ] + attr[:, IDX_EDGE_OD]
    check(bool(np.all(flags == 1)), "every edge row must have exactly one of edge_is_adjacent, edge_is_od")
