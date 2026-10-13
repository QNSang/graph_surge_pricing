"""Build immutable snapshots + hex market states from the hex_features Parquet partitions."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import DatasetRelease, Hex, HexMarketState, Snapshot
from app.domain.policies import fmt, quantize
from app.ingestion.dataset_loader import ActiveDataset, HexRow, node_mapping_version

FEATURE_COLUMNS = ["ts", "hex_id", "demand_5m", "idle_supply_t", "effective_supply_t", "current_surge_t"]
SURGE_SOURCE_COLUMN = "current_surge_t"


def snapshot_id_for(dataset_id: str, region_id: str, cutoff: datetime, nm_version: str) -> str:
    key = f"{dataset_id}|{region_id}|{cutoff.isoformat()}|{nm_version}"
    return "snap_" + hashlib.sha256(key.encode()).hexdigest()[:16]


def _clean(value) -> float | None:
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def market_row(raw: dict, precision: int, source_version: str) -> dict:
    """Missing values stay null with a reason; never replaced by 0 (spec §3.4)."""
    reasons: dict[str, str] = {}
    demand = _clean(raw.get("demand_5m"))
    idle = _clean(raw.get("idle_supply_t"))
    eff = _clean(raw.get("effective_supply_t"))
    surge = _clean(raw.get(SURGE_SOURCE_COLUMN))
    for name, value in (("demand", demand), ("idle_supply", idle), ("effective_supply", eff), ("surge_base", surge)):
        if value is None:
            reasons[name] = "MISSING_IN_SOURCE"
    observed = None
    if demand is None or eff is None:
        reasons["observed_ds"] = "INPUT_MISSING"
    elif eff <= 0:
        reasons["observed_ds"] = "ZERO_EFFECTIVE_SUPPLY"
    else:
        observed = demand / eff
    base = None if surge is None else quantize(Decimal(repr(surge)), precision)
    return {
        "demand": demand,
        "idle_supply": idle,
        "effective_supply": eff,
        "observed_ds": observed,
        "surge_base": base,
        "bidding_source_version": source_version if base is not None else None,
        "null_reasons": reasons,
    }


def ensure_release_and_hexes(session: Session, ds: ActiveDataset, hexes: list[HexRow], region_id: str) -> str:
    nm = node_mapping_version([h.hex_id for h in hexes])
    session.execute(
        insert(DatasetRelease)
        .values(
            dataset_id=ds.dataset_id,
            dataset_name=ds.dataset_id,
            dataset_version=str(ds.manifest.get("layout_version", "1")),
            fingerprint=ds.fingerprint,
            source_path=str(ds.root.as_posix()),
            schema_version=ds.schema_version,
            timezone=ds.timezone,
            snapshot_minutes=ds.snapshot_minutes,
            metadata_={
                "start_date": ds.start_date.isoformat(),
                "end_exclusive": ds.end_exclusive.isoformat(),
                "hex_count": ds.manifest.get("hex_count"),
                "days": ds.manifest.get("days"),
                "feature_version": ds.manifest.get("feature_version"),
                "limitations": ds.manifest.get("limitations", []),
            },
        )
        .on_conflict_do_nothing(index_elements=["dataset_id"])
    )
    session.execute(
        insert(Hex)
        .values(
            [
                {
                    "hex_id": h.hex_id,
                    "region_id": region_id,
                    "node_mapping_version": nm,
                    "node_index": h.node_index,
                    "zone": h.zone,
                    "ring": h.ring,
                    "lat": h.lat,
                    "lng": h.lng,
                    "polygon": h.polygon,
                    "neighbors": h.neighbors,
                }
                for h in hexes
            ]
        )
        .on_conflict_do_nothing(index_elements=["hex_id"])
    )
    return nm


def import_snapshots(
    session: Session,
    ds: ActiveDataset,
    *,
    region_id: str,
    nm_version: str,
    from_date: date,
    to_date: date,
    precision: int,
) -> list[str]:
    """Import every snapshot whose partition date is in [from_date, to_date]. Idempotent (ON CONFLICT DO NOTHING)."""
    tz = ZoneInfo(ds.timezone)
    hex_ids = set(session.scalars(select(Hex.hex_id).where(Hex.node_mapping_version == nm_version)))
    source_version = f"{ds.dataset_id}:{SURGE_SOURCE_COLUMN}"
    imported: list[str] = []
    day = from_date
    while day <= to_date:
        part = ds.root / "features" / "hex_features" / f"date={day.isoformat()}"
        files = sorted(part.glob("*.parquet"))
        if not files:
            day += timedelta(days=1)
            continue
        rows = pq.read_table(files, columns=FEATURE_COLUMNS).to_pylist() if len(files) > 1 else pq.read_table(
            files[0], columns=FEATURE_COLUMNS
        ).to_pylist()
        by_ts: dict[datetime, list[dict]] = defaultdict(list)
        for r in rows:
            by_ts[r["ts"]].append(r)
        snap_values, market_values = [], []
        for ts in sorted(by_ts):
            cutoff = ts.replace(tzinfo=tz) if ts.tzinfo is None else ts
            sid = snapshot_id_for(ds.dataset_id, region_id, cutoff, nm_version)
            group = [r for r in by_ts[ts] if r["hex_id"] in hex_ids]
            snap_values.append(
                {
                    "snapshot_id": sid,
                    "dataset_id": ds.dataset_id,
                    "region_id": region_id,
                    "cutoff_ts": cutoff,
                    "forecast_ts": None,
                    "node_mapping_version": nm_version,
                    "snapshot_version": "1",
                    "data_kind": "SYNTHETIC",
                    "hex_count": len(group),
                }
            )
            for r in group:
                market_values.append(
                    {"snapshot_id": sid, "hex_id": r["hex_id"], "cutoff_ts": cutoff, **market_row(r, precision, source_version)}
                )
            imported.append(sid)
        if snap_values:
            session.execute(insert(Snapshot).values(snap_values).on_conflict_do_nothing())
            for i in range(0, len(market_values), 5000):
                session.execute(insert(HexMarketState).values(market_values[i : i + 5000]).on_conflict_do_nothing())
        session.commit()
        day += timedelta(days=1)
    return imported


def fmt_base(value: Decimal | None) -> str | None:
    return fmt(value)
