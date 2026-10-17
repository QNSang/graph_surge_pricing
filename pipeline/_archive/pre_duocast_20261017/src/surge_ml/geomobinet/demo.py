"""Small deterministic schema fixture, NOT a realistic marketplace benchmark."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


def write_demo(folder: Path, *, steps: int = 160, nodes: int = 7, seed: int = 42) -> Path:
    if steps < 100 or nodes < 2:
        raise ValueError("Demo requires at least 100 snapshots and 2 nodes")
    folder = Path(folder).resolve()
    if folder.exists():
        raise ValueError(f"Demo destination already exists; choose a new folder: {folder}")
    folder.mkdir(parents=True)
    rng = np.random.default_rng(seed)
    hexes = [f"synthetic_{i:03d}" for i in range(nodes)]
    times = pd.date_range("2026-01-05", periods=steps, freq="5min", tz="Asia/Ho_Chi_Minh")
    distance = np.linspace(0.5, 6.0, nodes)
    geo = pd.DataFrame({"hex_id": hexes, "distance_to_cbd_km": distance,
                        "east_offset_km": np.linspace(-3.0, 3.0, nodes),
                        "north_offset_km": np.linspace(1.0, -1.0, nodes),
                        "road_neighbor_count": [1] + [2] * (nodes - 2) + [1],
                        "available_at": times[0]})
    spatial = []
    for i in range(nodes - 1):
        for src, dst in ((i, i + 1), (i + 1, i)):
            spatial.append({"source_hex": hexes[src], "target_hex": hexes[dst],
                            "distance_km": 1.0, "road_detour_ratio": 1.2,
                            "available_at": times[0]})
    market, mobility = [], []
    previous_demand = np.full(nodes, 12.0)
    previous_supply = np.full(nodes, 10.0)
    for k, ts in enumerate(times):
        demand = np.maximum(0, np.rint(0.8 * previous_demand + 0.2 * (12 + 4 * np.sin(k / 12))
                                      + rng.normal(0, 1, nodes)))
        supply = np.maximum(0, np.rint(0.85 * previous_supply + 0.15 * (11 + 2 * np.cos(k / 16))
                                      + rng.normal(0, 1, nodes)))
        for i, hex_id in enumerate(hexes):
            market.append({"timestamp": ts, "hex_id": hex_id,
                           "demand_5m": demand[i], "idle_supply_t": supply[i],
                           "backlog_t": max(0, demand[i] - supply[i]),
                           "eta_sec_t": 120.0 + 10 * max(0, demand[i] - supply[i]),
                           "base_surge": 1.0, "available_at": ts, "event_time": ts})
        # Directed physical-transition-shaped fixtures, with truly empty snapshots.
        if k % 11:
            for i in range(nodes - 1):
                src, dst = (i, i + 1) if k % 2 else (i + 1, i)
                mobility.append({"timestamp": ts, "origin_hex": hexes[src], "dest_hex": hexes[dst],
                                 "flow_5m": int(rng.integers(1, 4)), "eta_min": 2.0,
                                 "distance_km": 1.0, "available_at": ts,
                                 "od_cbd_distance_delta": distance[src] - distance[dst]})
        previous_demand, previous_supply = demand, supply
    pd.DataFrame(market).to_csv(folder / "market.csv", index=False)
    geo.to_csv(folder / "hex_geo.csv", index=False)
    pd.DataFrame(spatial).to_csv(folder / "spatial_edges.csv", index=False)
    pd.DataFrame(mobility).to_csv(folder / "od.csv", index=False)
    metadata = {"dataset_id": f"smg_schema_fixture_{steps}_{nodes}_{seed}", "synthetic": True,
                "point_in_time": True, "mobility_semantics": "physical_driver_transitions",
                "node_order": hexes, "static_as_of": str(times[0]),
                "feature_definition_version": "smg_canonical_minimal_v1",
                "warning": "Synthetic software test fixture; not forecasting benchmark evidence"}
    (folder / "meta.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    config = {"study_id": "smg-schema-smoke", "seeds": [seed],
              "variants": ["persistence", "geomobinet_smg"], "output_dir": "runs",
              "data": {"market": "market.csv", "geo": "hex_geo.csv", "spatial": "spatial_edges.csv",
                       "mobility": "od.csv", "metadata": "meta.json", "validate_h3": False,
                       "spatial_features": ["distance_km", "road_detour_ratio"]},
              "model": {"hidden": 16, "geo_hidden": 8, "heads": 2, "head_hidden": 8},
              "train": {"epochs": 2, "batch_size": 8, "eval_batch_size": 16, "num_threads": 2}}
    path = folder / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path
