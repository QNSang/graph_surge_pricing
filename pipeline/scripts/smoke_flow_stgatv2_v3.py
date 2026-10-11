"""Real Mock V3 forward/backward probe, without training or looking at test data.

Reads only the first day's first 20 cutoff snapshots and their observed OD
edges. Outputs are from RANDOMLY INITIALIZED weights and are NOT forecast
performance. No oracle data or future edges enter any model input.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch

from surge_ml.config import ModelConfig
from surge_ml.data.batch import make_batch
from surge_ml.data.dataset import DerivedData
from surge_ml.data.scaler import fit_zscore
from surge_ml.data.target import build_targets
from surge_ml.features import VARIANTS
from surge_ml.models.dual_gru_gatv2 import build_model, forward_batch
from surge_ml.training.losses import dual_loss, target_mask

ROOT = Path(__file__).resolve().parents[2]


def source_slice(root: Path, count: int = 20) -> tuple[DerivedData, dict]:
    manifest = json.loads((root / "meta/manifest.json").read_text(encoding="utf-8"))
    contract = json.loads((root / "meta/feature_contract.json").read_text(encoding="utf-8"))
    if not all(manifest.get(k) for k in (
            "raw_integrity_pass", "feature_integrity_pass", "clean_validation_pass")):
        raise AssertionError("Source release is not validated")
    if len(contract["node_features"]) != 40 or len(contract["edge_features"]) != 10:
        raise AssertionError("Unexpected feature contract")
    date = manifest["start_date"]
    node_file = root / "features" / "hex_features" / f"date={date}" / "part.parquet"
    edge_file = root / "features" / "graph_edges" / f"date={date}" / "part.parquet"
    nodes = pq.read_table(node_file, columns=["ts", "hex_id", *contract["node_features"]]).to_pandas()
    timestamps = pd.DatetimeIndex(sorted(nodes.ts.unique())[:count])
    hexes = contract["hex_ids"]
    grid = pd.MultiIndex.from_product([timestamps, hexes], names=["ts", "hex_id"])
    aligned = nodes.set_index(["ts", "hex_id"]).reindex(grid)
    if aligned.isnull().any().any():
        raise AssertionError("Incomplete real Mock V3 node grid")
    x = aligned[contract["node_features"]].to_numpy(dtype=np.float32).reshape(count, len(hexes), 40)

    e = pq.read_table(edge_file, columns=[
        "ts", "src_hex", "dst_hex", *contract["edge_features"]]).to_pandas()
    e = e[e.ts.isin(timestamps)].sort_values(
        ["ts", "src_hex", "dst_hex", "edge_is_od"], kind="stable")
    lut = {hex_id: i for i, hex_id in enumerate(hexes)}
    src = e.src_hex.map(lut).to_numpy(np.int64)
    dst = e.dst_hex.map(lut).to_numpy(np.int64)
    if (src < 0).any() or (dst < 0).any():
        raise AssertionError("OD edges point outside the current hex grid")
    attrs = e[contract["edge_features"]].to_numpy(np.float32)
    counts = e.groupby("ts", sort=True).size().reindex(timestamps, fill_value=0).to_numpy()
    ptr = np.concatenate(([0], np.cumsum(counts))).astype(np.int64)
    y, b, b32 = build_targets(x)
    train_cut = 14
    nm, ns = fit_zscore(x[:train_cut], 1e-6)
    em, es = fit_zscore(attrs[:ptr[train_cut]], 1e-6)
    data = DerivedData.from_raw(x, y, b, b32, src, dst, attrs, ptr,
                                scalers={"node_mean": nm, "node_std": ns,
                                         "edge_mean": em, "edge_std": es},
                                splits={"train": (0, 14), "val": (14, 18), "test": (18, 20)})
    return data, {"dataset_id": manifest["dataset_id"],
                  "data_fingerprint": manifest["data_fingerprint"],
                  "day": date, "n_edges_loaded": len(attrs),
                  "cutoff_timestamps": [str(timestamps[15]), str(timestamps[16])]}


def run(root: Path) -> dict:
    torch.manual_seed(42)
    torch.set_num_threads(2)
    data, origin = source_slice(root)
    small = ModelConfig(gru_hidden=32, neighbor_hidden=16, gat_layers=1,
                        gat_heads=4, head_hidden=32, dropout=0)
    model = build_model(VARIANTS["flow_stgatv2_full"], small).eval()
    cutoffs = np.array([15, 16], np.int64)
    full = make_batch(data, cutoffs, VARIANTS["flow_stgatv2_full"])
    self_batch = make_batch(data, cutoffs, VARIANTS["flow_stgatv2_self"])
    od = full["edge_relation"] == 1
    t0 = perf_counter()
    with torch.no_grad():
        pred = forward_batch(model, full)
        pred_self = forward_batch(model, self_batch)
        alternative = {k: v.clone() for k, v in full.items()}
        alternative["edge_history"][od, :, 8] += 2.0
        pred_edge_perturbed = forward_batch(model, alternative)
        flipped = {k: v.clone() for k, v in full.items()}
        flipped["edge_index"][:, od] = torch.flip(flipped["edge_index"][:, od], dims=[0])
        pred_direction_flipped = forward_batch(model, flipped)
    elapsed = perf_counter() - t0

    def mad(p):
        return float((pred["graph"] - p["graph"]).abs().mean().item())
    invariant = all(torch.equal(pred["local"], p["local"]) for p in (
        pred_self, pred_edge_perturbed, pred_direction_flipped))
    model.zero_grad(set_to_none=True)
    model.train()
    out = forward_batch(model, full)
    total, _ = dual_loss(out, full["y"], target_mask(full["y"], full["b"]),
                         beta=1.0, lambda_local=0.3)
    if total is None:
        raise AssertionError("No usable ground truth in this isolated smoke sample")
    total.backward()
    gradients = {
        "shared_gru": float(model.encoder.weight_ih_l0.grad.norm().item()),
        "edge_temporal_gru": float(model.edge_temporal.weight_ih_l0.grad.norm().item()),
        "od_inbound": float(model.od_messages.in_value[0].weight.grad.norm().item()),
        "od_outbound": float(model.od_messages.out_value[0].weight.grad.norm().item()),
        "local_head": float(model.head_local[0].weight.grad.norm().item()),
    }
    changes = {
        "real_graph_vs_self_only_mean_abs_change_log_q": mad(pred_self),
        "od_eta_edge_perturbation_mean_abs_change_log_q": mad(pred_edge_perturbed),
        "od_direction_flip_mean_abs_change_log_q": mad(pred_direction_flipped),
    }
    passed = (invariant and all(v > 0 and np.isfinite(v) for v in gradients.values())
              and all(v > 1e-9 and np.isfinite(v) for v in changes.values())
              and all(torch.isfinite(p).all() for p in pred.values()))
    report = {**origin, "status": "PASS" if passed else "FAIL",
              "purpose": "Untrained network forward/backward wiring diagnostic; not MAE or pricing uplift",
              "model": "flow_stgatv2_full", "window_steps": data.window,
              "n_nodes": data.n_nodes, "batch_size": len(cutoffs),
              "edge_counts": {
                  "adjacency": int((full["edge_relation"] == 0).sum().item()),
                  "od": int(od.sum().item()),
                  "synthetic_self": int((full["edge_relation"] == 2).sum().item()),
              },
              "historical_od_presence_fraction": float(full["edge_history_mask"][od].float().mean().item()),
              "model_parameters": sum(p.numel() for p in model.parameters()),
              "forward_four_calls_seconds": elapsed,
              "local_head_invariant_under_edge_changes": invariant,
              "untrained_output": {
                  "local_log_q_mean": float(pred["local"].mean().item()),
                  "graph_log_q_mean": float(pred["graph"].mean().item()),
              },
              "graph_sensitivity": changes, "nonzero_gradient_norms": gradients}
    if not passed:
        raise AssertionError(json.dumps(report, ensure_ascii=False))
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", default="data/hcm_mock_v3_90d_seed42_temporal_od")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    root, out = (ROOT / args.source).resolve(), (ROOT / args.out).resolve()
    if not root.is_relative_to(ROOT / "data"):
        raise ValueError("Dataset must be inside repo data/")
    if not out.is_relative_to(ROOT / "artifacts") or out.exists() or out.suffix != ".json":
        raise ValueError("Output must be a new JSON file under artifacts/")
    result = run(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                   encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(out),
                      "graph_sensitivity": result["graph_sensitivity"],
                      "n_edges": result["edge_counts"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
