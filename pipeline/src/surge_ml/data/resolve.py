"""Tìm nguồn chỉ đọc và tính khoá cache derived."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from surge_ml.data.validation import check, check_contract
from surge_ml.errors import SurgeError
from surge_ml.features import END_GAP, SNAPSHOTS_PER_DAY, WARMUP, WINDOW, Splits, split_bounds

DERIVE_VERSION = "w4_logratio_v2"  # v2: scaler fit on the train split only


@dataclass
class Source:
    root: Path
    manifest: dict
    contract: dict
    node_files: list[Path]
    edge_files: list[Path]
    split_days: dict[str, list[int]]  # 1-based inclusive days
    splits: Splits  # snapshot bounds [a, z)

    @property
    def n_snapshots(self) -> int:
        return self.manifest["days"] * SNAPSHOTS_PER_DAY


def load_source(root: Path, dataset_id: str, split_days: dict | None = None) -> Source:
    """Đọc và kiểm tra hợp đồng nguồn; ngày split lấy từ `split_days` (train.yaml) hoặc manifest."""
    meta = root / "meta"
    check((meta / "manifest.json").is_file(), f"no meta/manifest.json under {root}")
    manifest = json.loads((meta / "manifest.json").read_text(encoding="utf-8"))
    contract = json.loads((meta / "feature_contract.json").read_text(encoding="utf-8"))
    check_contract(manifest, contract, dataset_id)
    node_files = sorted((root / "features" / "hex_features").glob("date=*/*.parquet"))
    edge_files = sorted((root / "features" / "graph_edges").glob("date=*/*.parquet"))
    days = manifest.get("days")
    check(len(node_files) == days, f"expected {days} hex_features partitions, got {len(node_files)}")
    check(len(edge_files) == days, f"expected {days} graph_edges partitions, got {len(edge_files)}")
    split_days = split_days or manifest.get("suggested_split_days_inclusive")
    check(split_days is not None, "no split days: set data.split_days or suggested_split_days_inclusive in the manifest")
    split_days = {s: [int(d) for d in v] for s, v in split_days.items()}
    try:
        splits = split_bounds(split_days, days)
    except ValueError as exc:
        raise SurgeError("SOURCE", str(exc)) from exc
    return Source(root, manifest, contract, node_files, edge_files, split_days, splits)


def derived_key(src: Source, std_floor: float) -> str:
    """Băm đặc tả derive và thông số file; sửa nguồn đổi mtime/size nên đổi khoá."""
    stats = [(p.relative_to(src.root).as_posix(), p.stat().st_size, p.stat().st_mtime_ns)
             for p in [src.root / "meta" / "feature_contract.json", *src.node_files, *src.edge_files]]
    spec = {"version": DERIVE_VERSION, "dataset_id": src.manifest["dataset_id"],
            "data_fingerprint": src.manifest.get("data_fingerprint"), "window": WINDOW, "splits": src.splits, "warmup": WARMUP, "end_gap": END_GAP, "std_floor": std_floor, "files": stats}
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]
