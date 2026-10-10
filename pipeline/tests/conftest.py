from pathlib import Path

import numpy as np
import pytest
import yaml

from surge_ml.config import load_config
from surge_ml.data.dataset import DerivedData
from surge_ml.data.scaler import fit_zscore
from surge_ml.data.target import build_targets
from surge_ml.features import SNAPSHOTS_PER_DAY, split_bounds

# 30-day calendar split 21/4/5; real runs read the days from the source manifest.
DAYS = 30
SPLIT_DAYS = {"train": [1, 21], "val": [22, 25], "test": [26, 30]}
SPLITS = split_bounds(SPLIT_DAYS, DAYS)
N_SNAPSHOTS = DAYS * SNAPSHOTS_PER_DAY


def synthetic_data(n_nodes: int = 4, seed: int = 0) -> DerivedData:
    """Full-length grid with tiny N: per snapshot, a ring of adjacency edges plus one OD edge 0 -> 2."""
    rng = np.random.default_rng(seed)
    x = rng.poisson(3.0, size=(N_SNAPSHOTS, n_nodes, 40)).astype(np.float32)
    y, b, b32 = build_targets(x)
    src, dst, rows = [], [], []
    for i in range(n_nodes):
        src.append(i), dst.append((i + 1) % n_nodes), rows.append([1, 0])
    src.append(0), dst.append(2), rows.append([0, 1])
    per_k = len(src)
    edge_src = np.tile(np.array(src, np.int64), N_SNAPSHOTS)
    edge_dst = np.tile(np.array(dst, np.int64), N_SNAPSHOTS)
    attr = rng.random((per_k * N_SNAPSHOTS, 10)).astype(np.float32)
    attr[:, :2] = np.tile(np.array(rows, np.float32), (N_SNAPSHOTS, 1))
    ptr = np.arange(N_SNAPSHOTS + 1, dtype=np.int64) * per_k
    train_end = SPLITS["train"][1]
    nm, ns = fit_zscore(x[:train_end], 1e-6)
    em, es = fit_zscore(attr[: ptr[train_end]], 1e-6)
    scalers = {"node_mean": nm, "node_std": ns, "edge_mean": em, "edge_std": es}
    return DerivedData.from_raw(x, y, b, b32, edge_src, edge_dst, attr, ptr, scalers, splits=SPLITS)


@pytest.fixture(scope="session")
def data() -> DerivedData:
    return synthetic_data()


def write_config(tmp: Path, **train) -> Path:
    cfg = {
        "study_id": "test", "seeds": [1], "variants": ["persistence", "gru_gatv2_40"], "runs_root": "runs",
        "data": {"source_root": "src", "derived_root": "derived", "dataset_id": "x"},
        "model": {"gru_hidden": 8, "neighbor_hidden": 4, "gat_layers": 1, "gat_heads": 2, "head_hidden": 8,
                  "dropout": 0.1},
        "train": {"device": "cpu", "batch_size": 8, "eval_batch_size": 16, "epochs": 3, "scheduler": "none",
                  "limit_batches": 3, "patience": 10, **train},
        "tracking": {"enabled": False},
    }
    path = tmp / "train.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


@pytest.fixture
def cfg(tmp_path):
    return load_config(write_config(tmp_path))
