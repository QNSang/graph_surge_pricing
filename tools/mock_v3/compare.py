"""Compare two immutable clean_v1 mock releases on the exact same day/cell grid.

Reads only point-in-time node feature partitions, never modifies datasets.
Example:
  python tools/mock_v3/compare.py --v2 data/hcm_data_2 --v3 data/hcm_mock_v3_90d_seed42_temporal_od --out artifacts/mock_v3_90d_comparison.json
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = ["ts", "hex_id", "demand_5m", "idle_supply_t", "effective_supply_t"]


def read_nodes(dataset: Path):
    meta = json.loads((dataset / "meta/manifest.json").read_text(encoding="utf-8"))
    data = ds.dataset(dataset / "features/hex_features", format="parquet", partitioning="hive").to_table(columns=REQUIRED).to_pandas()
    data = data.sort_values(["ts", "hex_id"])
    n = int(meta["hex_count"])
    if data.duplicated(["ts", "hex_id"]).any() or len(data) != int(meta["days"]) * 288 * n:
        raise AssertionError("Invalid node/time grid")
    return meta, data, n


def summary(dataset: Path):
    meta, f, n = read_nodes(dataset)
    d = f["demand_5m"].to_numpy(dtype=float).reshape(-1, n)
    s = f["effective_supply_t"].to_numpy(dtype=float).reshape(-1, n)
    idle = f["idle_supply_t"].to_numpy(dtype=float).reshape(-1, n)
    state = np.where(d > s + 1e-6, 2, np.where(d + 1e-6 < s, 0, 1)).astype(np.int8)
    code = state[:-1].astype(np.int16) * 3 + state[1:]
    trans = np.bincount(code.reshape(-1), minlength=9).reshape((3, 3))
    episodes = {}
    for label, mask in (("surplus", 0), ("shortage", 2)):
        lengths = []
        for col in state.T:
            boundaries = np.flatnonzero(np.r_[True, col[1:] != col[:-1], True])
            lengths.extend(int(hi - lo) for lo, hi in zip(boundaries[:-1], boundaries[1:])
                           if col[lo] == mask)
        episodes[label] = {"count": len(lengths), "median_min": float(5 * np.median(lengths)) if lengths else 0,
                           "p90_min": float(5 * np.percentile(lengths, 90)) if lengths else 0}
    q = (d + 1) / (s + 1)
    return {
        "dataset_id": meta["dataset_id"], "data_fingerprint": meta.get("data_fingerprint"),
        "days": int(meta["days"]), "node_rows": int(state.size),
        "zero_demand_share": float((d == 0).mean()),
        "demand_mean": float(d.mean()), "effective_supply_mean": float(s.mean()),
        "idle_supply_mean": float(idle.mean()),
        "shortage_share": float((state == 2).mean()), "surplus_share": float((state == 0).mean()),
        "balanced_share": float((state == 1).mean()),
        "state_order": ["surplus", "balanced", "shortage"],
        "transition_counts_5m": trans.tolist(),
        "change_share_5m": float((state[:-1] != state[1:]).mean()),
        "direct_surplus_shortage_flip_share_5m": float(
            (((state[:-1] == 0) & (state[1:] == 2)) |
             ((state[:-1] == 2) & (state[1:] == 0))).mean()),
        "episode_minutes": episodes,
        "smoothed_q": {"p50": float(np.quantile(q, .5)), "p90": float(np.quantile(q, .9)),
                       "p99": float(np.quantile(q, .99))},
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--v2", required=True)
    p.add_argument("--v3", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    v2, v3, target = (ROOT / a.v2).resolve(), (ROOT / a.v3).resolve(), (ROOT / a.out).resolve()
    if ROOT / "artifacts" not in target.parents or target.exists():
        raise ValueError("Output must be a new file under artifacts/")
    old, new = summary(v2), summary(v3)
    if old["days"] != new["days"] or old["node_rows"] != new["node_rows"]:
        raise AssertionError("Both releases must cover equal day/hex grids")
    delta = {key: float(new[key] - old[key]) for key in (
        "zero_demand_share", "demand_mean", "effective_supply_mean", "shortage_share",
        "change_share_5m", "direct_surplus_shortage_flip_share_5m")}
    report = {"old": old, "new": new, "delta_v3_minus_v2": delta,
              "caveat": "Synthetic scenario comparison, not evidence of real-world calibration or GAT performance."}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(target), "delta": delta}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
