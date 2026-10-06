"""data.py - doc snapshot, kiem tra, chia train/val/test co purge, dung batch."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import pickle
import re
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import yaml

import features as F

HERE = Path(__file__).resolve().parent

# ----------------------------------------------------------------------------- config
_LGBM = {"n_estimators": int, "learning_rate": float, "num_leaves": int, "min_child_samples": int,
         "subsample": float, "colsample_bytree": float, "early_stopping_rounds": int}
SCHEMA = {
    "note": str,
    "seed": int,
    "data": {"path": str, "train": ("list", str), "val": str, "test": str, "purge_min": int, "window": int,
             "horizons": ("list", int), "eps": float, "snapshot_min": int, "debug_days": ("opt", int),
             "cache": bool},
    "features": {"eta_edges_min": ("list", float), "eta_weights": ("list", float), "travel_window_min": int},
    "model": {"name": str, "gru_hidden": int, "gat_layers": int, "gat_heads": int, "head_hidden": int,
              "dropout": float, "lgbm": _LGBM},
    "loss": {"level": {"weight": float, "huber_delta": float, "rho": float},
             "diff": {"weight": float},
             "rank": {"weight": float, "temperature": float, "margin": float},
             "short": {"weight": float, "tau_s": float}},
    "train": {"lr": float, "epochs": int, "batch_size": int, "eval_batch_size": int, "patience": int,
              "select_by": str, "weight_decay": float, "grad_clip": float,
              "warn_const_ratio": float, "warn_leak_margin": float},
    "eval": {"margin_m": float, "min_volume": float},
}
MODELS = ("logds", "logds_eff", "lgbm", "gru_only", "gru_gatv2")


def _check(schema, value, path):
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            raise ValueError(f"config: '{path}' phai la mapping")
        extra = set(value) - set(schema)
        if extra:
            raise ValueError(f"config: key la {sorted(extra)} trong '{path or '<root>'}'")
        missing = set(schema) - set(value)
        if missing:
            raise ValueError(f"config: thieu key {sorted(missing)} trong '{path or '<root>'}'")
        for k, s in schema.items():
            _check(s, value[k], f"{path}.{k}" if path else k)
    elif isinstance(schema, tuple) and schema[0] == "list":
        if not isinstance(value, list):
            raise ValueError(f"config: '{path}' phai la list")
        for i, v in enumerate(value):
            _check(schema[1], v, f"{path}[{i}]")
    elif isinstance(schema, tuple) and schema[0] == "opt":
        if value is not None:
            _check(schema[1], value, path)
    else:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool) if schema is float else \
            isinstance(value, schema) and not (schema is int and isinstance(value, bool))
        if not ok:
            raise ValueError(f"config: '{path}' phai la {schema.__name__}, nhan {value!r}")


def load_config(path) -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    _check(SCHEMA, cfg, "")
    if cfg["model"]["name"] not in MODELS:
        raise ValueError(f"config: model.name phai thuoc {MODELS}")
    if not re.fullmatch(r"val_pairacc_\d+", cfg["train"]["select_by"]):
        raise ValueError("config: train.select_by dang val_pairacc_<h>")
    if int(cfg["train"]["select_by"].rsplit("_", 1)[1]) not in cfg["data"]["horizons"]:
        raise ValueError("config: train.select_by tro toi horizon khong co trong data.horizons")
    step = cfg["data"]["snapshot_min"]
    for h in cfg["data"]["horizons"]:
        if h % step:
            raise ValueError("config: horizon phai chia het cho snapshot_min")
    if len(cfg["features"]["eta_edges_min"]) != len(cfg["features"]["eta_weights"]):
        raise ValueError("config: eta_edges_min va eta_weights phai cung do dai")
    _week_range(cfg["data"]["train"], 2)
    _week_range([cfg["data"]["val"]], 1)
    _week_range([cfg["data"]["test"]], 1)
    return cfg


def _week_range(spec, n):
    """['week1','week6'] -> ngay 1..42 (1-based, bao ca hai dau)."""
    if len(spec) != n:
        raise ValueError(f"config: split can {n} phan tu, nhan {spec}")
    w = []
    for s in spec:
        m = re.fullmatch(r"week(\d+)", s)
        if not m or int(m.group(1)) < 1:
            raise ValueError(f"config: '{s}' phai co dang weekN")
        w.append(int(m.group(1)))
    if w[0] > w[-1]:
        raise ValueError(f"config: khoang tuan nguoc {spec}")
    return (w[0] - 1) * 7 + 1, w[-1] * 7


# ----------------------------------------------------------------------------- doc + kiem tra
def _dates(root: Path, name: str):
    ds = sorted(p.name.split("=", 1)[1] for p in (root / name).glob("date=*"))
    d = pd.to_datetime(ds)
    assert len(ds) and (np.diff(d.values).astype("timedelta64[D]").astype(int) == 1).all(), f"{name}: ngay khong lien tuc"
    return ds


def _read(root: Path, name: str, dates):
    return pd.concat([pd.read_parquet(root / name / f"date={d}" / "part.parquet") for d in dates], ignore_index=True)


def validate_snap(snap: pd.DataFrame, hex_ids: set, step_min: int):
    num = snap[["demand", "supply", "eta_sec"]]
    assert not num.isna().any().any(), "snapshot co NaN"
    assert not snap[["ts", "hex_id"]].isna().any().any(), "snapshot co ts/hex NaN"
    unknown = set(snap["hex_id"].unique()) - hex_ids
    assert not unknown, f"hex la trong snapshot: {sorted(unknown)[:3]}"
    assert not snap.duplicated(["ts", "hex_id"]).any(), "trung (ts, hex)"
    ts = np.sort(snap["ts"].unique()).astype("datetime64[ns]").astype("int64")
    assert (np.diff(ts) == step_min * 60 * 10**9).all(), f"thieu snapshot: ts khong lien tuc moi {step_min} phut"


def validate_orders(o: pd.DataFrame, hex_ids: set):
    assert not o[["origin_hex", "dest_hex", "created_ts", "est_trip_duration_min"]].isna().any().any(), "orders co NaN"
    assert not (set(o["origin_hex"]) | set(o["dest_hex"])) - hex_ids, "canh tro ra ngoai tap hex"
    assert (o["est_trip_duration_min"] > 0).all(), "est_trip_duration <= 0"
    assert (o["pickup_ts"].isna() == o["dropoff_ts"].isna()).all(), "pickup/dropoff khong di doi"
    done = o["dropoff_ts"].notna()
    assert (o.loc[done, "dropoff_ts"] > o.loc[done, "pickup_ts"]).all(), "dropoff <= pickup"
    assert (o.loc[done, "pickup_ts"] >= o.loc[done, "created_ts"]).all(), "pickup < created"


# ----------------------------------------------------------------------------- split
@dataclasses.dataclass
class Norm:
    node_mean: np.ndarray
    node_std: np.ndarray
    edge_mean: np.ndarray
    edge_std: np.ndarray


def fit_norm(grid: F.Grid) -> Norm:
    rows = grid.node[grid.present]
    nm, ns = rows.mean(0), rows.std(0)
    em, es = grid.eattr.mean(0), grid.eattr.std(0)
    return Norm(nm, np.where(ns < 1e-6, 1.0, ns), em, np.where(es < 1e-6, 1.0, es))


def apply_norm(grid: F.Grid, nz: Norm) -> F.Grid:
    return dataclasses.replace(grid, node=((grid.node - nz.node_mean) / nz.node_std).astype(np.float32),
                               eattr=((grid.eattr - nz.edge_mean) / nz.edge_std).astype(np.float32))


class Split:
    """Mot split: grid goc (D/S/b...), grid da chuan hoa (dua vao model) va danh sach k hop le."""

    def __init__(self, name, grid: F.Grid, nz: Norm, cfg):
        d = cfg["data"]
        self.name, self.raw, self.cfg = name, grid, cfg
        self.grid = apply_norm(grid, nz)
        self.window = d["window"]
        self.steps = [h // d["snapshot_min"] for h in d["horizons"]]
        purge = d["purge_min"] // d["snapshot_min"]
        T = len(grid.ts)
        # mau hop le: cua so + horizon nam tron trong khoang da cat `purge` o cuoi
        self.ks = np.arange(self.window - 1, T - purge - max(self.steps))
        assert len(self.ks) > 0, f"split {name}: khong du du lieu sau purge"
        self.N = len(grid.hexes)

    def __len__(self):
        return len(self.ks)

    def targets(self, ks):
        ys, ms, vs = zip(*[F.target_y(self.raw, k, self.steps) for k in ks])
        y, m, v = np.stack(ys), np.stack(ms), np.stack(vs)
        b = np.stack([F.persistence_b(self.raw, k) for k in ks])
        return y, m, v, b

    def batch(self, ks, device="cpu"):
        W, N = self.window, self.N
        xs, eis, eas, ebs, mins = [], [], [], [], []
        for bi, k in enumerate(ks):
            x, ei, ea, m = F.build_features(self.grid, int(k), W)
            xs.append(x); eis.append(ei + bi * N); eas.append(ea); mins.append(m)
            ebs.append(np.full(ei.shape[1], bi))
        y, my, vol, b = self.targets(ks)
        mask_in = np.stack(mins)
        t = lambda a, dt=torch.float32: torch.as_tensor(np.ascontiguousarray(a), dtype=dt, device=device)
        return {
            "x": t(np.stack(xs)), "b": t(b), "y": t(y), "vol": t(vol),
            "mask_in": t(mask_in, torch.bool), "mask_y": t(my & mask_in[:, :, None], torch.bool),
            "edge_index": t(np.concatenate(eis, axis=1), torch.long), "edge_attr": t(np.concatenate(eas)),
            "edge_batch": t(np.concatenate(ebs), torch.long),
            "d_t": t(self.raw.d[ks]), "s_t": t(self.raw.s[ks]), "seff_t": t(self.raw.s_eff[ks]),
            "ks": torch.as_tensor(ks),
        }

    def iterate(self, batch_size, shuffle=False, rng=None, device="cpu"):
        ks = self.ks.copy()
        if shuffle:
            (rng or np.random.default_rng()).shuffle(ks)
        for i in range(0, len(ks), batch_size):
            yield self.batch(ks[i:i + batch_size], device)

    def flat(self, ks):
        """Du lieu phang cho lgbm: feature hien tai + trend (x_t - x_{t-1}, x_t - x_{t-W+1}).

        Tra ve X [S*N, f], plus y, b, mask, vol cung hinh."""
        node = self.grid.node
        nd = len(F.NODE_DYN)
        cur = node[ks]                                            # [S, N, F]
        d1 = cur[..., :nd] - node[ks - 1][..., :nd]
        dw = cur[..., :nd] - node[ks - (self.window - 1)][..., :nd]
        X = np.concatenate([cur, d1, dw], axis=-1)
        y, m, v, b = self.targets(ks)
        mask_in = np.stack([self.raw.present[k - self.window + 1:k + 1].all(0) for k in ks])
        return X, y, m & mask_in[:, :, None], v, b


def _hash(cfg, root):
    keys = {"data": {k: v for k, v in cfg["data"].items() if k not in ("cache",)}, "features": cfg["features"],
            "root": str(root)}
    return hashlib.sha1(json.dumps(keys, sort_keys=True).encode()).hexdigest()[:12]


def build_splits(cfg, log=print):
    """Doc du lieu that, kiem tra, dung grid cho train/val/test, fit chuan hoa tren train."""
    d = cfg["data"]
    root = (HERE / d["path"]).resolve()
    cache_f = HERE / "cache" / f"{_hash(cfg, root)}.pkl"
    if d["cache"] and cache_f.exists():
        log(f"[data] cache: {cache_f.name}")
        with open(cache_f, "rb") as f:
            blob = pickle.load(f)
    else:
        blob = _build_blob(cfg, root, log)
        if d["cache"]:
            cache_f.parent.mkdir(exist_ok=True)
            with open(cache_f, "wb") as f:
                pickle.dump(blob, f, protocol=4)
    nz = blob["norm"]
    splits = {n: Split(n, g, nz, cfg) for n, g in blob["grids"].items()}
    return splits, nz


def _build_blob(cfg, root, log):
    d = cfg["data"]
    hexes = pd.read_parquet(root / "hexes.parquet").sort_values("hex_id").reset_index(drop=True)
    hex_ids = hexes["hex_id"].tolist()
    hex2idx = {h: i for i, h in enumerate(hex_ids)}
    dist = F.haversine_km(hexes["lat"].to_numpy(), hexes["lng"].to_numpy())
    snap_dates = _dates(root, "hex_snapshot_5min")
    order_dates = _dates(root, "orders")
    weather = pd.concat([pd.read_parquet(root / "weather_5min" / f"date={x}" / "part.parquet") for x in _dates(root, "weather_5min")])

    spans = {"train": _week_range(d["train"], 2), "val": _week_range([d["val"]], 1), "test": _week_range([d["test"]], 1)}
    if d["debug_days"] is not None:
        spans = {n: (lo, min(hi, lo + d["debug_days"] - 1)) for n, (lo, hi) in spans.items()}
    for n, (lo, hi) in spans.items():
        assert hi <= len(snap_dates), f"split {n}: can ngay {hi}, du lieu chi co {len(snap_dates)} ngay"
    log(f"[data] {root}  {len(snap_dates)} ngay ({snap_dates[0]}..{snap_dates[-1]}), {len(hex_ids)} hex")

    raw_orders, snaps = {}, {}
    for n, (lo, hi) in spans.items():
        snap = _read(root, "hex_snapshot_5min", snap_dates[lo - 1:hi])
        validate_snap(snap, set(hex_ids), d["snapshot_min"])
        od = _read(root, "orders", order_dates[max(lo - 2, 0):hi])      # + 1 ngay dem: chuyen dang chay luc dau split
        validate_orders(od, set(hex_ids))
        snaps[n], raw_orders[n] = snap, F.orders_from_frame(od, hex2idx)
        log(f"[data] {n:5s} ngay {lo}-{hi}  snapshot {len(snap):,}  orders {len(od):,}")

    pair_est = F.pair_est_matrix(raw_orders["train"], dist)             # fallback fit chi tren train
    grids = {}
    for n in spans:
        grids[n] = F.build_grid(snaps[n], raw_orders[n], hexes, weather, pair_est, dist, cfg)
    nz = fit_norm(grids["train"])
    return {"grids": grids, "norm": nz, "hexes": hex_ids}
