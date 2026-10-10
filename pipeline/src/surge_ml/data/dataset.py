"""Bản trong RAM của thư mục derived, đã chuẩn hoá bằng scaler fit trên train (~0.4 GB mỗi 30 ngày)."""

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from surge_ml.data.scaler import apply_zscore
from surge_ml.features import HORIZON, IDX_EDGE_ADJ, WINDOW, Splits, candidates, shift_target


@dataclass
class DerivedData:
    x: np.ndarray  # [T, N, 40] z-scored
    y: np.ndarray  # [T, N] log-ratio target (NaN where unavailable)
    b: np.ndarray  # [T, N] bypass log((D+1)/(S_eff+1))
    b32: np.ndarray  # [T, N] bypass log((D+1)/(S_idle+1))
    edge_src: np.ndarray  # [E] sorted by snapshot
    edge_dst: np.ndarray
    edge_attr: np.ndarray  # [E, 10] z-scored
    edge_is_adj: np.ndarray  # [E] bool, from the raw flag
    edge_ptr: np.ndarray  # [T + 1] CSR offsets by snapshot
    splits: Splits = field(default_factory=dict)  # snapshot bounds [a, z) per split, from the derived manifest
    path: Path | None = None
    manifest: dict = field(default_factory=dict)
    window: int = WINDOW  # snapshots per input window
    horizon: int = HORIZON  # y[k] = b[k + horizon]
    _keep: dict = field(default_factory=dict, repr=False)

    @property
    def n_nodes(self) -> int:
        return self.x.shape[1]

    def candidates(self, split: str) -> np.ndarray:
        return candidates(split, self.splits, self.window)

    def with_temporal(self, window: int = WINDOW, horizon: int = HORIZON) -> "DerivedData":
        """Bản dùng chung mảng với cửa sổ và horizon mới; y tính lại từ b, b và b32 giữ nguyên tại cutoff k."""
        if window < 1:
            raise ValueError(f"window must be >= 1, got {window}")
        y = self.y if horizon == self.horizon else shift_target(self.b, horizon)
        return DerivedData(**{**self.__dict__, "y": y, "window": window, "horizon": horizon, "_keep": self._keep})

    @classmethod
    def from_raw(cls, x, y, b, b32, edge_src, edge_dst, edge_attr, edge_ptr, scalers, **kw) -> "DerivedData":
        return cls(x=apply_zscore(x, scalers["node_mean"], scalers["node_std"]), y=y, b=b, b32=b32,
                   edge_src=edge_src, edge_dst=edge_dst,
                   edge_attr=apply_zscore(edge_attr, scalers["edge_mean"], scalers["edge_std"]),
                   edge_is_adj=edge_attr[:, IDX_EDGE_ADJ] == 1, edge_ptr=edge_ptr, **kw)

    @classmethod
    def load(cls, path: Path, window: int = WINDOW, horizon: int = HORIZON) -> "DerivedData":
        # x and edge_attr are z-scored into a new array, so their raw copies stay on disk (memmap).
        arrays = {n: np.load(path / f"{n}.npy", mmap_mode="r" if n in ("x", "edge_attr") else None) for n in
                  ["x", "y", "b", "b32", "edge_src", "edge_dst", "edge_attr", "edge_ptr"]}
        scalers = dict(np.load(path / "scalers.npz"))
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        splits = {s: tuple(v["bounds"]) for s, v in manifest["splits"].items()}
        data = cls.from_raw(**arrays, scalers=scalers, splits=splits, path=path, manifest=manifest)
        return data.with_temporal(window, horizon)

    def keep_mask(self, relations: tuple[str, ...]) -> np.ndarray:
        """Các dòng cạnh giữ lại cho một tập quan hệ; ablation graph lọc dòng, không lọc thuộc tính."""
        if relations not in self._keep:
            keep = np.zeros(len(self.edge_src), bool)
            if "adj" in relations:
                keep |= self.edge_is_adj
            if "od" in relations:
                keep |= ~self.edge_is_adj
            self._keep[relations] = keep
        return self._keep[relations]
