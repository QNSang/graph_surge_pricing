"""Read-only queries over immutable source data (snapshots, hexes, market states)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Row, and_, or_, select
from sqlalchemy.orm import Session

from app.db.models import DatasetRelease, Hex, HexMarketState, Snapshot


def get(session: Session, snapshot_id: str) -> Snapshot | None:
    return session.get(Snapshot, snapshot_id)


def release(session: Session, dataset_id: str) -> DatasetRelease | None:
    return session.get(DatasetRelease, dataset_id)


def list_page(
    session: Session,
    *,
    region_id: str | None,
    dataset_id: str | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    after: tuple[datetime, str] | None,
    limit: int,
) -> list[Snapshot]:
    q = select(Snapshot)
    if region_id:
        q = q.where(Snapshot.region_id == region_id)
    if dataset_id:
        q = q.where(Snapshot.dataset_id == dataset_id)
    if from_ts:
        q = q.where(Snapshot.cutoff_ts >= from_ts)
    if to_ts:
        q = q.where(Snapshot.cutoff_ts <= to_ts)
    if after:
        ts, sid = after
        q = q.where(or_(Snapshot.cutoff_ts > ts, and_(Snapshot.cutoff_ts == ts, Snapshot.snapshot_id > sid)))
    return list(session.scalars(q.order_by(Snapshot.cutoff_ts, Snapshot.snapshot_id).limit(limit)))


def neighbours_in_time(session: Session, snap: Snapshot) -> tuple[str | None, str | None]:
    """Previous/next snapshot ids of the same dataset/region/node mapping (for replay navigation)."""
    base = select(Snapshot.snapshot_id).where(
        Snapshot.dataset_id == snap.dataset_id,
        Snapshot.region_id == snap.region_id,
        Snapshot.node_mapping_version == snap.node_mapping_version,
    )
    prev_id = session.scalar(base.where(Snapshot.cutoff_ts < snap.cutoff_ts).order_by(Snapshot.cutoff_ts.desc()).limit(1))
    next_id = session.scalar(base.where(Snapshot.cutoff_ts > snap.cutoff_ts).order_by(Snapshot.cutoff_ts).limit(1))
    return prev_id, next_id


def market_with_hexes(session: Session, snapshot_id: str) -> list[Row[tuple[HexMarketState, Hex]]]:
    return list(
        session.execute(
            select(HexMarketState, Hex)
            .join(Hex, Hex.hex_id == HexMarketState.hex_id)
            .where(HexMarketState.snapshot_id == snapshot_id)
            .order_by(Hex.node_index)
        ).all()
    )


def market_state(session: Session, snapshot_id: str, hex_id: str) -> HexMarketState | None:
    return session.get(HexMarketState, (snapshot_id, hex_id))


def hexes(session: Session, region_id: str) -> list[Hex]:
    return list(session.scalars(select(Hex).where(Hex.region_id == region_id).order_by(Hex.node_index)))


def get_hex(session: Session, hex_id: str) -> Hex | None:
    return session.get(Hex, hex_id)


def history(
    session: Session,
    *,
    hex_id: str,
    dataset_id: str | None,
    region_id: str | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    after: datetime | None,
    limit: int,
) -> list[HexMarketState]:
    q = select(HexMarketState).where(HexMarketState.hex_id == hex_id)
    if dataset_id or region_id:
        q = q.join(Snapshot, Snapshot.snapshot_id == HexMarketState.snapshot_id)
        if dataset_id:
            q = q.where(Snapshot.dataset_id == dataset_id)
        if region_id:
            q = q.where(Snapshot.region_id == region_id)
    if from_ts:
        q = q.where(HexMarketState.cutoff_ts >= from_ts)
    if to_ts:
        q = q.where(HexMarketState.cutoff_ts <= to_ts)
    if after:
        q = q.where(HexMarketState.cutoff_ts > after)
    return list(session.scalars(q.order_by(HexMarketState.cutoff_ts).limit(limit)))
