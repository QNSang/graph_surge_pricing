"""Per-hex market history (spec §8.4, §12.3). Values come only from hex_market_states, never proposals/overrides."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.domain.enums import SeriesKind
from app.domain.policies import fmt
from app.domain.timefmt import decode_cursor, encode_cursor, iso
from app.repositories import snapshot_repository
from app.services.snapshot_service import METRIC_METADATA

# series -> (market column, metadata key, value is decimal string?)
SERIES = {
    SeriesKind.BASE_BIDDING: ("surge_base", "surge_base", True),
    SeriesKind.DEMAND: ("demand", "demand", False),
    SeriesKind.EFFECTIVE_SUPPLY: ("effective_supply", "effective_supply", False),
    SeriesKind.OBSERVED_DS: ("observed_ds", "observed_ds", False),
}


def history(
    session: Session,
    *,
    hex_id: str,
    series: str,
    from_ts: datetime | None,
    to_ts: datetime | None,
    dataset_id: str | None,
    region_id: str | None,
    cursor: str | None,
    limit: int,
    timezone: str,
) -> dict:
    if series == SeriesKind.FORECAST_DS:
        raise AppError(
            "SERIES_UNAVAILABLE",
            "FORECAST_DS is not stored by the backend for this dataset.",
            {"series": series, "available": [s.value for s in SERIES]},
        )
    if series not in SERIES:
        raise AppError("INVALID_REQUEST", "Unknown series.", {"series": series, "available": [s.value for s in SERIES]})
    if snapshot_repository.get_hex(session, hex_id) is None:
        raise AppError("NOT_FOUND", "Hex not found.", {"hex_id": hex_id})
    column, meta_key, as_decimal = SERIES[SeriesKind(series)]
    after = decode_cursor(cursor, 1)
    rows = snapshot_repository.history(
        session,
        hex_id=hex_id,
        dataset_id=dataset_id,
        region_id=region_id,
        from_ts=from_ts,
        to_ts=to_ts,
        after=datetime.fromisoformat(after[0]) if after else None,
        limit=limit + 1,
    )
    page = rows[:limit]
    minutes = _cadence(session, page)
    points: list[dict] = []
    prev_ts = None
    for m in page:
        # Keep gaps explicit: missing snapshots become null points with a reason instead of being interpolated.
        if prev_ts is not None and minutes:
            gap = prev_ts + timedelta(minutes=minutes)
            while gap < m.cutoff_ts:
                points.append({"ts": iso(gap), "value": None, "reason": "NO_SNAPSHOT"})
                gap += timedelta(minutes=minutes)
        raw = getattr(m, column)
        point = {"ts": iso(m.cutoff_ts), "value": fmt(raw) if as_decimal else raw}
        if raw is None:
            point["reason"] = m.null_reasons.get(column, "MISSING")
        points.append(point)
        prev_ts = m.cutoff_ts
    meta = METRIC_METADATA[meta_key]
    return {
        "hex_id": hex_id,
        "series_kind": series,
        "unit": meta["unit"],
        "metric_definition": meta["definition"],
        "source": "hex_market_states",
        "timezone": timezone,
        "snapshot_minutes": minutes,
        "points": points,
        "next_cursor": encode_cursor(page[-1].cutoff_ts.isoformat()) if len(rows) > limit else None,
    }


def _cadence(session: Session, rows) -> int | None:
    if not rows:
        return None
    snap = snapshot_repository.get(session, rows[0].snapshot_id)
    release = snapshot_repository.release(session, snap.dataset_id)
    return release.snapshot_minutes
