"""Hằng số hợp đồng V1.2 (cố định) và các dataclass dùng chung."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from surge_ml.features import END_GAP, HORIZON, PURGE, WARMUP, WINDOW, warmup

# ---- identities ---------------------------------------------------------
PROJECT_ID = "graph_surge_pricing"
PIPELINE_CONTRACT_VERSION = "v1.2"
FEATURE_CONTRACT_ID = "hex40_edge10_w4_v1_2"
AGGREGATE_FEATURE_CONTRACT_ID = FEATURE_CONTRACT_ID
TARGET_CONTRACT_ID = "ds_logratio_eps1_h5_v1_2"
GRAPH_CONTRACT_ID = "directed_relations_self_v1"
MODEL_CONTRACT_ID = "dual_gru_gatv2_h5_v1_2"
SOURCE_FEATURE_CONTRACT_ID = "hex40_edge10_v2.1"
SOURCE_LAYOUT_ID = "hcm_v2_parquet_tree_v1"
INVENTORY_POLICY = "raw_features_burn_in_v1"
NORMALIZATION_ID = "zscore_train_only_w4_v1"
PRIMARY_METRIC = "val/graph/mae_q/h5"
DERIVATION_VERSION = "w4_logratio_v1"

# ---- shapes -------------------------------------------------------------
# Defaults only; a run's window and horizon come from data.window_steps / data.horizon_steps.
W = WINDOW             # t-15, t-10, t-5, t
H = HORIZON            # horizon steps (5 min)
PURGE_STEPS = PURGE
N_NODES = 61
F_CONTEXT = 37
F_ALL = 40
E_RAW = 10
E_INTERNAL = 11        # 10 raw attributes + is_self
IDX_DEMAND = 0
IDX_EFFECTIVE_SUPPLY = 29

# Snapshot count and split bounds depend on the dataset: see features.split_bounds and data/resolve.py.
WARMUP_STEPS = WARMUP
END_GAP_STEPS = END_GAP

# invalid_reason_bits
BIT_BEYOND_END = 1
BIT_CROSS_SPLIT = 2
BIT_NONFINITE = 4
BIT_NEGATIVE_D = 8
BIT_NONPOSITIVE_S = 16
BIT_OVERFLOW = 32

# relation types in typed edge rows
REL_ADJACENCY = 0
REL_OD = 1

SYNTHETIC_SELF_FLAGS = (1.0,)  # is_self
OBSERVED_FLAGS = (0.0,)

SOURCE_SCHEMA_SHA256_AT_INSPECTION = "b6673dd8290caea3ac76cc22a18b60cf8acf024e2344f785e315002312401995"

INPUT_TABLES = {
    "node_features": "features/hex_features",
    "graph_edges": "features/graph_edges",
    "hex_snapshot": "raw/hex_snapshot",
    "hexes": "raw/hexes",
    "orders": "raw/orders",
    "weather": "raw/weather",
    "burn_in_orders": "burn_in/orders",
    "burn_in_hex_snapshot": "burn_in/hex_snapshot",
    "burn_in_weather": "burn_in/weather",
}
INVENTORY_ROOTS = ("raw", "features", "burn_in")
FORBIDDEN_ROOTS = ("oracle", "_archive")

HEAD_ORDER = ("local", "graph")


def split_candidates(a: int, z: int, window: int = W) -> range:
    """Các cutoff của split [a, z): đủ 60 phút lịch sử feature cho cả cửa sổ và bỏ phần đuôi cuối split."""
    return range(a + warmup(window), z - END_GAP_STEPS)


# ---- shared dataclasses -------------------------------------------------
@dataclass(frozen=True)
class SourceDatasetRef:
    root: str
    dataset_id: str
    source_training_fingerprint: str
    source_parquet_sha256: str
    source_schema_sha256: str
    source_feature_contract_sha256: str
    source_manifest_file_sha256: str
    source_manifest_semantic_sha256: str
    hex_ids: tuple[str, ...]
    node_features: tuple[str, ...]
    edge_features: tuple[str, ...]

    def identity(self) -> dict[str, Any]:
        return {
            "source_dataset_id": self.dataset_id,
            "source_training_fingerprint": self.source_training_fingerprint,
            "source_parquet_sha256": self.source_parquet_sha256,
            "source_schema_sha256": self.source_schema_sha256,
            "source_feature_contract_sha256": self.source_feature_contract_sha256,
            "source_layout_id": SOURCE_LAYOUT_ID,
        }


@dataclass(frozen=True)
class DerivedDatasetRef:
    root: str
    derived_fingerprint: str
    derivation_spec_hash: str
    payload_sha256: str
    manifest_file_sha256: str
    source: dict[str, Any]
    split_manifest_sha256: str
    scaler_sha256: dict[str, str]
    candidate_counts: dict[str, int]


@dataclass
class GraphBatch:
    """Một minibatch đã ghép; tensor nhãn tách riêng khỏi đầu vào model."""

    x: Any                     # float32 [B,W,N,F]
    edge_index: Any            # int64   [2,E]
    edge_attr: Any             # float32 [E,12]
    edge_ptr: Any              # int64   [B+1]
    y: Any                     # float32 [B,N,1]  (invalid -> 0 placeholder)
    target_valid: Any          # bool    [B,N,1]
    k: Any                     # int64   [B]
    raw_d_t: Any               # float64 [B,N]
    raw_seff_t: Any            # float64 [B,N]
    q_h5: Any                  # float64 [B,N]  (invalid -> NaN)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def batch_size(self) -> int:
        return int(self.x.shape[0])

    @property
    def n_nodes(self) -> int:
        return int(self.x.shape[2])

    def inputs(self) -> tuple[Any, Any, Any]:
        return self.x, self.edge_index, self.edge_attr

    def to(self, device: Any) -> "GraphBatch":
        import torch

        def mv(v: Any) -> Any:
            return v.to(device) if isinstance(v, torch.Tensor) else v

        return GraphBatch(
            x=mv(self.x), edge_index=mv(self.edge_index), edge_attr=mv(self.edge_attr),
            edge_ptr=mv(self.edge_ptr), y=mv(self.y), target_valid=mv(self.target_valid),
            k=mv(self.k), raw_d_t=self.raw_d_t, raw_seff_t=self.raw_seff_t, q_h5=self.q_h5,
            meta=self.meta,
        )


def empty_f64(*shape: int) -> np.ndarray:
    return np.full(shape, np.nan, dtype=np.float64)
