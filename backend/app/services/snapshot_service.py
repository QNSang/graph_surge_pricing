"""Snapshot listing/detail/summary and the unified snapshot read model (spec §12.4)."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import Policy
from app.core.errors import AppError
from app.db.models import Snapshot
from app.domain.timefmt import decode_cursor, encode_cursor, iso
from app.repositories import recommendation_repository, snapshot_repository
from app.services import recommendation_service

METRIC_METADATA = {
    "demand": {"unit": "requests / 5 min", "definition": "Ride requests in the 5-minute window ending at cutoff_ts."},
    "idle_supply": {"unit": "drivers", "definition": "Idle drivers in the hex at cutoff_ts."},
    "effective_supply": {
        "unit": "drivers",
        "definition": "Effective supply at cutoff_ts (dataset feature effective_supply_t).",
    },
    "observed_ds": {
        "unit": "ratio",
        "definition": "Observed D/S = demand / effective_supply at cutoff_ts; null when effective_supply = 0.",
    },
    "surge_base": {
        "unit": "multiplier",
        "definition": "Historical bidding surge at cutoff_ts (dataset feature current_surge_t); never a proposal or override.",
    },
}


def serialize_snapshot(s: Snapshot) -> dict:
    return {
        "snapshot_id": s.snapshot_id,
        "dataset_id": s.dataset_id,
        "region_id": s.region_id,
        "cutoff_ts": iso(s.cutoff_ts),
        "forecast_ts": iso(s.forecast_ts),
        "node_mapping_version": s.node_mapping_version,
        "snapshot_version": s.snapshot_version,
        "data_kind": s.data_kind,
        "hex_count": s.hex_count,
    }


def _require(session: Session, snapshot_id: str) -> Snapshot:
    snap = snapshot_repository.get(session, snapshot_id)
    if snap is None:
        raise AppError("SNAPSHOT_NOT_FOUND", "Snapshot not found.", {"snapshot_id": snapshot_id})
    return snap


def list_snapshots(
    session: Session,
    *,
    region_id: str | None,
    dataset_id: str | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    cursor: str | None,
    limit: int,
) -> dict:
    after = decode_cursor(cursor, 2)
    after_key = (datetime.fromisoformat(after[0]), after[1]) if after else None
    rows = snapshot_repository.list_page(
        session,
        region_id=region_id,
        dataset_id=dataset_id,
        from_ts=from_ts,
        to_ts=to_ts,
        after=after_key,
        limit=limit + 1,
    )
    page = rows[:limit]
    next_cursor = encode_cursor(page[-1].cutoff_ts.isoformat(), page[-1].snapshot_id) if len(rows) > limit else None
    return {"items": [serialize_snapshot(s) for s in page], "next_cursor": next_cursor}


def detail(session: Session, snapshot_id: str) -> dict:
    snap = _require(session, snapshot_id)
    release = snapshot_repository.release(session, snap.dataset_id)
    prev_id, next_id = snapshot_repository.neighbours_in_time(session, snap)
    sets = recommendation_repository.sets_for_snapshot(session, snapshot_id)
    current = recommendation_repository.latest_published_set(session, snapshot_id)
    current_id = current.recommendation_set_id if current else None
    return {
        **serialize_snapshot(snap),
        "dataset": {
            "dataset_id": release.dataset_id,
            "fingerprint": release.fingerprint,
            "schema_version": release.schema_version,
            "timezone": release.timezone,
            "snapshot_minutes": release.snapshot_minutes,
        },
        "recommendation_sets": [recommendation_service.serialize_set(s, current_id) for s in sets],
        "current_recommendation_set_id": current_id,
        "navigation": {"previous_snapshot_id": prev_id, "next_snapshot_id": next_id},
    }


def _summarise(views) -> dict:
    by_action = Counter(v.rec.action for v in views)
    by_elig = Counter(v.eligibility.state.value for v in views)
    by_decision = Counter(v.decision.status if v.decision else "UNDECIDED" for v in views)
    actionable = sum(
        1
        for v in views
        if v.decision is None and v.eligibility.state.value == "ELIGIBLE" and v.rec.action in ("INCREASE", "DECREASE")
    )
    return {
        "total": len(views),
        "by_action": {a: by_action.get(a, 0) for a in ("INCREASE", "DECREASE", "HOLD", "REVIEW")},
        "by_eligibility": dict(by_elig),
        "by_decision_status": dict(by_decision),
        "accept_all_candidates": actionable,
    }


def summary(session: Session, snapshot_id: str, policy: Policy, demo_session_id: uuid.UUID | None) -> dict:
    _require(session, snapshot_id)
    rset, current_id, views = recommendation_service.views_for_snapshot(
        session, snapshot_id, policy, demo_session_id=demo_session_id
    )
    return {
        "snapshot_id": snapshot_id,
        "recommendation_set_id": rset.recommendation_set_id if rset else None,
        "demo_session_id": str(demo_session_id) if demo_session_id else None,
        **_summarise(views),
    }


def read_model(session: Session, snapshot_id: str, policy: Policy, demo_session_id: uuid.UUID | None) -> dict:
    """Map + queue + detail panel from ONE snapshot identity: market and proposals share the same cutoff."""
    snap = _require(session, snapshot_id)
    release = snapshot_repository.release(session, snap.dataset_id)
    prev_id, next_id = snapshot_repository.neighbours_in_time(session, snap)
    rset, current_id, views = recommendation_service.views_for_snapshot(
        session, snapshot_id, policy, demo_session_id=demo_session_id
    )
    by_hex = {v.rec.hex_id: v for v in views}
    hexes = []
    for market, hx in snapshot_repository.market_with_hexes(session, snapshot_id):
        view = by_hex.get(hx.hex_id)
        hexes.append(
            {
                "hex_id": hx.hex_id,
                "zone": hx.zone,
                "ring": hx.ring,
                "centroid": {"lat": hx.lat, "lng": hx.lng},
                "polygon": hx.polygon,
                "neighbors": hx.neighbors,
                "market": recommendation_service.serialize_market(market),
                "proposal": recommendation_service.serialize(view) if view else None,
            }
        )
    return {
        "snapshot": serialize_snapshot(snap),
        "dataset": {
            "dataset_id": release.dataset_id,
            "fingerprint": release.fingerprint,
            "timezone": release.timezone,
            "snapshot_minutes": release.snapshot_minutes,
        },
        "recommendation_set": recommendation_service.serialize_set(rset, current_id),
        "policy": policy.as_public_dict(),
        "demo_session_id": str(demo_session_id) if demo_session_id else None,
        "metric_metadata": METRIC_METADATA,
        "navigation": {"previous_snapshot_id": prev_id, "next_snapshot_id": next_id},
        "summary": _summarise(views),
        "hexes": hexes,
    }


def region_hexes(session: Session, region_id: str) -> dict:
    rows = snapshot_repository.hexes(session, region_id)
    if not rows:
        raise AppError("NOT_FOUND", "Region not found or has no hexes.", {"region_id": region_id})
    return {
        "region_id": region_id,
        "node_mapping_version": rows[0].node_mapping_version,
        "total": len(rows),
        "items": [
            {
                "hex_id": h.hex_id,
                "node_index": h.node_index,
                "zone": h.zone,
                "ring": h.ring,
                "centroid": {"lat": h.lat, "lng": h.lng},
                "polygon": h.polygon,
                "neighbors": h.neighbors,
            }
            for h in rows
        ],
    }
