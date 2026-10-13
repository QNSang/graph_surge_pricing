"""Resolve the active dataset through data/CURRENT.json + manifest (never hard-code path/days/hex count)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import h3
import pyarrow.parquet as pq
import yaml


@dataclass(frozen=True)
class ActiveDataset:
    dataset_id: str
    fingerprint: str
    root: Path
    schema_version: str
    timezone: str
    snapshot_minutes: int
    start_date: date
    end_exclusive: datetime
    manifest: dict


@dataclass(frozen=True)
class HexRow:
    hex_id: str
    node_index: int
    zone: str | None
    ring: int | None
    lat: float
    lng: float
    polygon: list[list[float]]
    neighbors: list[str]


def load_active_dataset(repo_root: Path) -> ActiveDataset:
    current = json.loads((repo_root / "data" / "CURRENT.json").read_text(encoding="utf-8"))
    root = repo_root / current["path"]
    manifest = json.loads((repo_root / current["manifest"]).read_text(encoding="utf-8"))
    schema = yaml.safe_load((repo_root / current["schema"]).read_text(encoding="utf-8")) or {}
    ds_block = schema.get("dataset", {}) if isinstance(schema, dict) else {}
    schema_version = str(schema.get("schema_version") or ds_block.get("version") or current.get("layout_version"))
    if manifest.get("data_fingerprint") != current["data_fingerprint"]:
        raise ValueError("CURRENT.json fingerprint does not match manifest; refusing to import")
    return ActiveDataset(
        dataset_id=current["dataset_id"],
        fingerprint=current["data_fingerprint"],
        root=root,
        schema_version=schema_version,
        timezone=manifest.get("timezone", "Asia/Ho_Chi_Minh"),
        snapshot_minutes=int(manifest.get("snapshot_minutes") or ds_block.get("snapshot_minutes")),
        start_date=date.fromisoformat(manifest["start_date"]),
        end_exclusive=datetime.fromisoformat(manifest["end_exclusive"]),
        manifest=manifest,
    )


def last_date(ds: ActiveDataset) -> date:
    return (ds.end_exclusive - timedelta(minutes=ds.snapshot_minutes)).date()


def node_mapping_version(hex_ids: list[str]) -> str:
    digest = hashlib.sha256("\n".join(sorted(hex_ids)).encode()).hexdigest()
    return f"nm_{digest[:12]}"


def load_hexes(ds: ActiveDataset) -> list[HexRow]:
    table = pq.read_table(ds.root / "raw" / "hexes" / "part.parquet").to_pylist()
    ids = sorted(r["hex_id"] for r in table)
    known = set(ids)
    index = {h: i for i, h in enumerate(ids)}
    rows = []
    for r in table:
        hid = r["hex_id"]
        boundary = [[lat, lng] for lat, lng in h3.cell_to_boundary(hid)]
        neighbors = sorted(n for n in h3.grid_disk(hid, 1) if n != hid and n in known)
        rows.append(
            HexRow(
                hex_id=hid,
                node_index=index[hid],
                zone=r.get("zone"),
                ring=r.get("ring"),
                lat=float(r["lat"]),
                lng=float(r["lng"]),
                polygon=boundary,
                neighbors=neighbors,
            )
        )
    return sorted(rows, key=lambda h: h.node_index)
