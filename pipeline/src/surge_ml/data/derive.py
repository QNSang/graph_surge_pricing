"""Parquet nguồn -> mảng numpy trong data/derived/d_<key>/. Nguồn chỉ đọc; build ghi vào thư mục tạm rồi đổi tên, nên cache hoặc đầy đủ hoặc không tồn tại."""

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from surge_ml.config import Config
from surge_ml.data.resolve import DERIVE_VERSION, Source, derived_key, load_source
from surge_ml.data.scaler import fit_zscore
from surge_ml.data.target import build_targets
from surge_ml.data.validation import check, check_edges, check_grid, check_nodes
from surge_ml.features import candidates

ARRAYS = ["x", "y", "b", "b32", "edge_src", "edge_dst", "edge_attr", "edge_ptr"]


def _ts_ns(table: pa.Table) -> np.ndarray:
    return table.column("ts").cast(pa.int64()).to_numpy()


def _index(grid: np.ndarray, ts: np.ndarray) -> np.ndarray:
    k = np.searchsorted(grid, ts)
    check(bool(np.all(k < len(grid))) and bool(np.all(grid[np.minimum(k, len(grid) - 1)] == ts)),
          "timestamp outside the snapshot grid")
    return k


def _hex_index(hexes: pd.Index, values: np.ndarray, what: str) -> np.ndarray:
    idx = hexes.get_indexer(values)
    check(bool(np.all(idx >= 0)), f"{what} contains hex ids outside the contract")
    return idx


def _npy(path: Path, shape: tuple, dtype) -> np.ndarray:
    return np.lib.format.open_memmap(path, mode="w+", dtype=dtype, shape=shape)


def _read_nodes(src: Source, hexes: pd.Index, tmp: Path) -> tuple[np.ndarray, np.ndarray]:
    """Đọc từng partition ngày vào tmp/x.npy [T, N, F]."""
    names = src.contract["node_features"]
    grid = np.unique(np.concatenate([np.unique(_ts_ns(pq.read_table(p, columns=["ts"]))) for p in src.node_files]))
    check_grid(grid, src.n_snapshots)
    x = _npy(tmp / "x.npy", (len(grid), len(hexes), len(names)), np.float32)
    counts = np.zeros((len(grid), len(hexes)), np.int32)
    for p in src.node_files:
        t = pq.read_table(p, columns=["ts", "hex_id", *names])
        k = _index(grid, _ts_ns(t))
        i = _hex_index(hexes, t.column("hex_id").to_numpy(zero_copy_only=False), "hex_features")
        x[k, i] = np.column_stack([t.column(c).to_numpy().astype(np.float32) for c in names])
        np.add.at(counts, (k, i), 1)
    check_nodes(x, counts)
    return grid, x


def _read_edges(src: Source, hexes: pd.Index, grid: np.ndarray, tmp: Path) -> dict[str, np.ndarray]:
    """Dòng cạnh sắp theo snapshot; mỗi partition ngày sắp cục bộ rồi ghi vào mảng cấp sẵn (số dòng lấy từ metadata parquet)."""
    names = src.contract["edge_features"]
    total = sum(pq.ParquetFile(p).metadata.num_rows for p in src.edge_files)
    edge_src, edge_dst = _npy(tmp / "edge_src.npy", (total,), np.int64), _npy(tmp / "edge_dst.npy", (total,), np.int64)
    attr = _npy(tmp / "edge_attr.npy", (total, len(names)), np.float32)
    counts = np.zeros(len(grid), np.int64)
    pos, last_k = 0, -1
    for p in src.edge_files:
        t = pq.read_table(p, columns=["ts", "src_hex", "dst_hex", *names])
        k = _index(grid, _ts_ns(t))
        if not len(k):
            continue
        check(int(k.min()) > last_k, f"{p.name}: edge snapshots overlap the previous partition")
        order = np.argsort(k, kind="stable")
        rows = slice(pos, pos + len(k))
        edge_src[rows] = _hex_index(hexes, t.column("src_hex").to_numpy(zero_copy_only=False), "graph_edges")[order]
        edge_dst[rows] = _hex_index(hexes, t.column("dst_hex").to_numpy(zero_copy_only=False), "graph_edges")[order]
        part = np.column_stack([t.column(c).to_numpy().astype(np.float32) for c in names])[order]
        check_edges(part)
        attr[rows] = part
        counts += np.bincount(k, minlength=len(grid))
        pos, last_k = pos + len(k), int(k.max())
    check(pos == total, f"read {pos} edge rows, parquet metadata says {total}")
    ptr = np.zeros(len(grid) + 1, np.int64)
    ptr[1:] = np.cumsum(counts)
    return {"edge_src": edge_src, "edge_dst": edge_dst, "edge_attr": attr, "edge_ptr": ptr}


def build(src: Source, out: Path, std_floor: float) -> None:
    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    hexes = pd.Index(src.contract["hex_ids"])
    grid, x = _read_nodes(src, hexes, tmp)
    edges = _read_edges(src, hexes, grid, tmp)
    y, b, b32 = build_targets(x)
    train_end = src.splits["train"][1]
    node_mean, node_std = fit_zscore(x[:train_end], std_floor)
    edge_mean, edge_std = fit_zscore(edges["edge_attr"][: edges["edge_ptr"][train_end]], std_floor)
    shape = {"T": int(x.shape[0]), "N": int(x.shape[1]), "F": int(x.shape[2]), "E": int(len(edges["edge_src"]))}

    for name, arr in {"y": y, "b": b, "b32": b32, "edge_ptr": edges["edge_ptr"]}.items():
        np.save(tmp / f"{name}.npy", arr)
    for arr in (x, edges["edge_src"], edges["edge_dst"], edges["edge_attr"]):
        arr.flush()
    del x, edges, arr  # close the memmaps; Windows cannot rename a directory with open files
    np.savez(tmp / "scalers.npz", node_mean=node_mean, node_std=node_std, edge_mean=edge_mean, edge_std=edge_std)
    manifest = {
        "derive_version": DERIVE_VERSION,
        "dataset_id": src.manifest["dataset_id"],
        "data_fingerprint": src.manifest.get("data_fingerprint"),
        "source_root": str(src.root),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "shape": shape,
        "first_ts": str(pd.Timestamp(grid[0])),
        "splits": {s: {"days": src.split_days[s], "bounds": list(bounds),
                       "candidates": int(len(candidates(s, src.splits)))} for s, bounds in src.splits.items()},
        "node_features": src.contract["node_features"],
        "edge_features": src.contract["edge_features"],
        "hex_ids": src.contract["hex_ids"],
        "std_floor": std_floor,
    }
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp, out)


def prepare(cfg: Config) -> Path:
    """Trả thư mục derived của config này, build nếu chưa có."""
    src = load_source(cfg.data.source_root, cfg.data.dataset_id, cfg.data.split_days)
    out = cfg.data.derived_root / f"d_{derived_key(src, cfg.data.std_floor)}"
    if not (out / "manifest.json").is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        build(src, out, cfg.data.std_floor)
    return out
