"""Point-in-time CSV/Parquet validation and chronological sample construction."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DataConfig, TARGETS

STEP = pd.Timedelta(minutes=5)


def read_table(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise ValueError(f"Missing input: {path}; use the four-table SMG schema, not legacy hex40 data")
    if "oracle" in (part.lower() for part in path.parts):
        raise ValueError("oracle data is forbidden as a model input")
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() in (".parquet", ".pq"):
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported table: {path}; expected CSV or Parquet")


def timestamps(values, timezone: str):
    result = pd.to_datetime(values, errors="raise")
    if result.isna().any():
        raise ValueError("Timestamp columns cannot contain nulls")
    if isinstance(result, pd.Series):
        return result.dt.tz_localize(timezone) if result.dt.tz is None else result.dt.tz_convert(timezone)
    result = pd.DatetimeIndex(result)
    return result.tz_localize(timezone) if result.tz is None else result.tz_convert(timezone)


def numeric(frame: pd.DataFrame, columns: list[str], name: str, cfg: DataConfig,
            nullable: tuple[str, ...] | list[str] = ()) -> np.ndarray:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{name}: missing columns {sorted(missing)}")
    values = frame[columns].apply(pd.to_numeric, errors="raise").to_numpy(dtype=np.float64, na_value=np.nan)
    for i, column in enumerate(columns):
        vector = values[:, i]
        if np.isinf(vector).any() or (column not in nullable and np.isnan(vector).any()):
            raise ValueError(f"{name}.{column}: nonfinite/missing value; no silent zero filling")
        if column not in cfg.signed_features and (vector < 0).any():
            raise ValueError(f"{name}.{column}: negative count/duration/distance")
    with np.errstate(over="ignore"):
        result = values.astype(np.float32)
    if np.isinf(result).any():
        raise ValueError(f"{name}: values overflow float32")
    return result


def check_available(frame: pd.DataFrame, name: str, cfg: DataConfig, meta: dict,
                    first_time: pd.Timestamp | None = None) -> None:
    cutoff = frame["timestamp"] if first_time is None else first_time
    if "available_at" in frame:
        available = timestamps(frame["available_at"], cfg.timezone)
        if (available > cutoff).any():
            raise ValueError(f"{name}: available_at is later than the feature cutoff")
    elif cfg.availability == "strict":
        if first_time is None or "static_as_of" not in meta:
            raise ValueError(f"{name}: strict availability requires available_at (static tables may use meta.static_as_of)")
        known = timestamps(pd.Series([meta["static_as_of"]]), cfg.timezone).iloc[0]
        if known > first_time:
            raise ValueError(f"{name}: static_as_of is after the first snapshot")
    elif meta.get("point_in_time") is not True:
        raise ValueError("snapshot_contract requires explicit meta.point_in_time=true; this is an upstream assertion")
    for column in ("event_time", "window_end"):
        if column in frame and (timestamps(frame[column], cfg.timezone) > cutoff).any():
            raise ValueError(f"{name}: {column} is after cutoff")


@dataclass
class Panel:
    timestamps: pd.DatetimeIndex
    hex_ids: list[str]
    dynamic: np.ndarray
    geo: np.ndarray
    spatial_index: np.ndarray
    spatial_attr: np.ndarray
    mobility_ptr: np.ndarray
    mobility_index: np.ndarray
    mobility_attr: np.ndarray
    target: np.ndarray
    metadata: dict
    fingerprint: str

    @property
    def n_nodes(self):
        return len(self.hex_ids)


def file_fingerprint(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode())
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def load_panel(cfg: DataConfig) -> Panel:
    meta = json.loads(cfg.metadata.read_text(encoding="utf-8"))
    if not meta.get("dataset_id"):
        raise ValueError("meta.dataset_id is required")
    if meta.get("mobility_semantics") != "physical_driver_transitions":
        raise ValueError("meta.mobility_semantics must be physical_driver_transitions; passenger/request OD is not valid")
    if not cfg.validate_h3 and meta.get("synthetic") is not True:
        raise ValueError("validate_h3=false is restricted to explicitly synthetic datasets")
    frames = {key: read_table(getattr(cfg, key)) for key in ("market", "geo", "spatial", "mobility")}
    market, geo, spatial, mobility = (frames[k].copy() for k in ("market", "geo", "spatial", "mobility"))
    for name, frame, keys in (("market", market, ["timestamp", "hex_id"]),
                              ("geo", geo, ["hex_id"]),
                              ("spatial", spatial, ["source_hex", "target_hex"]),
                              ("mobility", mobility, ["timestamp", "origin_hex", "dest_hex"])):
        if not set(keys) <= set(frame.columns) or frame[keys].isna().any().any():
            raise ValueError(f"{name}: missing/null key columns {keys}")
        if "timestamp" in keys:
            frame["timestamp"] = timestamps(frame["timestamp"], cfg.timezone)
        for key in set(keys) - {"timestamp"}:
            frame[key] = frame[key].astype(str)
        if frame.duplicated(keys).any():
            raise ValueError(f"{name}: duplicate {keys}; aggregate explicitly upstream")
    times = pd.DatetimeIndex(market["timestamp"].unique()).sort_values()
    if len(times) == 0 or not ((times[1:] - times[:-1]) == STEP).all():
        raise ValueError("market requires a complete five-minute timestamp grid")
    if any(t.minute % 5 or t.second or t.microsecond or t.nanosecond for t in times):
        raise ValueError("market timestamps must align to five-minute boundaries")
    nodes = list(meta.get("node_order", sorted(market["hex_id"].unique())))
    if not nodes or len(nodes) != len(set(nodes)) or set(nodes) != set(market["hex_id"]):
        raise ValueError("meta.node_order must contain each market hex exactly once")
    if len(market) != len(times) * len(nodes):
        raise ValueError("market has missing timestamp/hex rows; causal imputation must be explicit upstream")
    if set(geo["hex_id"]) != set(nodes):
        raise ValueError("hex_geo must contain exactly the market node set")
    if cfg.validate_h3:
        try:
            import h3
        except ImportError as exc:
            raise ValueError("H3 validation needs h3; install the geomobinet optional dependencies") from exc
        if any(not h3.is_valid_cell(h) or h3.get_resolution(h) != 7 for h in nodes):
            raise ValueError("Production data requires valid H3 resolution-7 IDs")
        if any(dst not in h3.grid_disk(src, 1) for src, dst in zip(spatial.source_hex, spatial.target_hex)):
            raise ValueError("spatial graph contains a non-ring-1 edge")
    check_available(market, "market", cfg, meta)
    check_available(mobility, "mobility", cfg, meta)
    check_available(geo, "geo", cfg, meta, times[0])
    check_available(spatial, "spatial", cfg, meta, times[0])
    node_map = {h: i for i, h in enumerate(nodes)}
    market = market.set_index(["timestamp", "hex_id"]).loc[
        pd.MultiIndex.from_product([times, nodes], names=["timestamp", "hex_id"])]
    dynamic = numeric(market, cfg.dynamic_features, "market", cfg, cfg.nullable_dynamic)
    dynamic = dynamic.reshape(len(times), len(nodes), -1)
    target = dynamic[:, :, [cfg.dynamic_features.index(k) for k in TARGETS]].copy()
    geo = geo.set_index("hex_id").loc[nodes]
    geo_values = numeric(geo, cfg.geo_features, "geo", cfg)

    def edge_arrays(frame, src, dst, columns, name):
        if not frame[src].isin(nodes).all() or not frame[dst].isin(nodes).all():
            raise ValueError(f"{name}: unknown node ID")
        if (frame[src] == frame[dst]).any():
            raise ValueError(f"{name}: self edges are not physical cross-hex transitions; residual retains local state")
        idx = np.stack([frame[src].map(node_map).to_numpy(dtype=np.int64),
                        frame[dst].map(node_map).to_numpy(dtype=np.int64)])
        return idx, numeric(frame, columns, name, cfg)

    pairs = set(zip(spatial.source_hex, spatial.target_hex))
    if any((dst, src) not in pairs for src, dst in pairs):
        raise ValueError("spatial graph must be bidirectional; mobility graph must not be symmetrized")
    sp_index, sp_attr = edge_arrays(spatial, "source_hex", "target_hex", cfg.spatial_features, "spatial")
    if not mobility["timestamp"].isin(times).all():
        raise ValueError("mobility timestamp is outside market grid")
    mobility = mobility.sort_values(["timestamp", "origin_hex", "dest_hex"])
    od_index, od_attr = edge_arrays(mobility, "origin_hex", "dest_hex", cfg.mobility_features, "mobility")
    for total, idle, busy in (("flow_5m", "idle_flow_5m", "busy_flow_5m"),
                              ("driver_flow_5m", "idle_driver_flow_5m", "busy_driver_flow_5m")):
        if {total, idle, busy} <= set(mobility.columns):
            if (mobility[idle] + mobility[busy] > mobility[total] + 1e-5).any():
                raise ValueError("mobility: idle + busy flow exceeds total driver flow")
    for delta in ("od_cbd_distance_delta", "od_cbd_distance_delta_km"):
        if delta in mobility and "distance_to_cbd_km" in geo:
            distance = geo["distance_to_cbd_km"]
            expected = mobility.origin_hex.map(distance) - mobility.dest_hex.map(distance)
            if not np.allclose(expected, mobility[delta], atol=1e-3):
                raise ValueError("mobility CBD delta must be origin distance minus destination distance")
    od_times = times.get_indexer(mobility["timestamp"])
    ptr = np.searchsorted(od_times, np.arange(len(times) + 1)).astype(np.int64)
    fingerprint = file_fingerprint([cfg.market, cfg.geo, cfg.spatial, cfg.mobility, cfg.metadata])
    return Panel(times, nodes, dynamic, geo_values, sp_index, sp_attr, ptr, od_index, od_attr,
                 target, meta, fingerprint)


def make_splits(n_times: int, cfg: DataConfig) -> dict[str, np.ndarray]:
    train_end = int(n_times * cfg.train_fraction)
    val_end = int(n_times * (cfg.train_fraction + cfg.val_fraction))
    result = {}
    for name, start, end in (("train", 0, train_end), ("val", train_end, val_end),
                              ("test", val_end, n_times)):
        low = max(cfg.history - 1, start - 1)
        if cfg.split_mode == "strict":
            low = start + cfg.history - 1
        if name != "train":
            low += cfg.embargo_steps
        result[name] = np.arange(low, end - cfg.horizon, dtype=np.int64)
        if result[name].size == 0:
            raise ValueError(f"No {name} samples after history/embargo; provide more snapshots")
    return result


def split_manifest(panel: Panel, splits: dict[str, np.ndarray], cfg: DataConfig) -> dict:
    return {name: {"samples": len(ks), "first_cutoff": str(panel.timestamps[ks[0]]),
                   "last_cutoff": str(panel.timestamps[ks[-1]]),
                   "first_target": str(panel.timestamps[ks[0] + cfg.horizon]),
                   "last_target": str(panel.timestamps[ks[-1] + cfg.horizon]),
                   "first_input": str(panel.timestamps[ks[0] - cfg.history + 1])}
            for name, ks in splits.items()}
