"""Synthetic seed for integration tests: 6 hexes, 3 snapshots, recommendation sets covering every action/eligibility."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import get_policy
from app.db.models import DatasetRelease, Hex, HexMarketState, Snapshot
from app.ingestion.recommendation_importer import persist_batch, register_policy, register_provider
from app.providers.base import OUTPUT_SCHEMA_VERSION, ProviderInfo, RecommendationBatch
from app.services.validation_service import validate_batch

DATASET_ID = "test_dataset"
FINGERPRINT = "fp_test"
REGION = "hcmc"
NM = "nm_test"
HEXES = ["h1", "h2", "h3", "h4", "h5", "h6"]
BASE = {"h1": "1.20", "h2": "1.50", "h3": "1.00", "h4": "1.10", "h5": "1.50", "h6": "1.00"}

# hex -> (action, surge_proposed). h5 is inconsistent (INVALID), h6 exceeds max_deviation (BLOCKED).
S1_RECS = {
    "h1": ("INCREASE", "1.40"),
    "h2": ("DECREASE", "1.30"),
    "h3": ("HOLD", "1.00"),
    "h4": ("REVIEW", None),
    "h5": ("INCREASE", "1.40"),
    "h6": ("INCREASE", "1.60"),
}

# Snapshot 4 is the end-to-end playground: several movable proposals.
S4_RECS = {
    "h1": ("INCREASE", "1.40"),
    "h2": ("DECREASE", "1.30"),
    "h3": ("HOLD", "1.00"),
    "h4": ("REVIEW", None),
    "h5": ("DECREASE", "1.30"),
    "h6": ("INCREASE", "1.20"),
}


@dataclass
class Seed:
    s1: str
    s2: str
    s3: str
    s4: str
    set_s4: str
    set_s1: str
    set_s3_old: str
    set_s3_new: str
    proposals: dict[str, str]  # S1 hex -> proposal_id
    s3_old_h1: str
    s3_new_h1: str


class _Fixed:
    def __init__(self, version: str):
        self.info = ProviderInfo(id="fixed_test_provider", version=version, kind="MOCK", description="test")


def _batch(snapshot_id: str, version: str, recs: dict, policy_version: str) -> RecommendationBatch:
    rows = []
    for hex_id, (action, proposed) in recs.items():
        rows.append(
            {
                "proposal_id": f"{snapshot_id}:{hex_id}",
                "hex_id": hex_id,
                "action": action,
                "surge_base": BASE[hex_id],
                "surge_proposed": proposed,
                "explanation": f"test {action}",
                "reason_codes": [] if action != "REVIEW" else ["LOCAL_BELOW_Q_MIN"],
                "evidence": {"q_local": 1.0},
            }
        )
    return RecommendationBatch(
        schema_version=OUTPUT_SCHEMA_VERSION,
        snapshot_id=snapshot_id,
        provider=_Fixed(version).info,
        policy_version=policy_version,
        generated_at=datetime.now(UTC),
        recommendations=rows,
        dataset_fingerprint=FINGERPRINT,
    )


def _publish(session: Session, snapshot_id: str, version: str, recs: dict) -> str:
    policy = get_policy()
    batch = _batch(snapshot_id, version, recs, policy.policy_version)
    report = validate_batch(
        batch, snapshot_id=snapshot_id, snapshot_hexes=set(HEXES), dataset_fingerprint=FINGERPRINT, policy=policy
    )
    result = persist_batch(session, batch, report, snapshot_id)
    session.commit()
    return result.recommendation_set_id


def seed(session: Session) -> Seed:
    from sqlalchemy import select

    from app.db.models import Recommendation

    policy = get_policy()
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    session.add(
        DatasetRelease(
            dataset_id=DATASET_ID,
            dataset_name="test",
            dataset_version="v0",
            fingerprint=FINGERPRINT,
            source_path="tests",
            schema_version="test",
            timezone="Asia/Ho_Chi_Minh",
            snapshot_minutes=5,
        )
    )
    for i, h in enumerate(HEXES):
        session.add(
            Hex(
                hex_id=h,
                region_id=REGION,
                node_mapping_version=NM,
                node_index=i,
                zone="core",
                ring=0,
                lat=10.77 + i * 0.01,
                lng=106.70,
                polygon=[[10.77, 106.70], [10.78, 106.71], [10.77, 106.72]],
                neighbors=[x for x in HEXES if x != h][:2],
            )
        )
    session.flush()
    t0 = datetime(2026, 1, 5, 8, 0, tzinfo=tz)
    ids = []
    # Offsets in minutes; 15 is deliberately missing so history has a gap (BE-22).
    for k, offset in enumerate((0, 5, 10, 20)):
        sid = f"snap_test_{k + 1}"
        ids.append(sid)
        ts = t0 + timedelta(minutes=offset)
        session.add(
            Snapshot(
                snapshot_id=sid,
                dataset_id=DATASET_ID,
                region_id=REGION,
                cutoff_ts=ts,
                node_mapping_version=NM,
                data_kind="SYNTHETIC",
                hex_count=len(HEXES),
            )
        )
        session.flush()
        for h in HEXES:
            zero = h == "h4"
            session.add(
                HexMarketState(
                    snapshot_id=sid,
                    hex_id=h,
                    cutoff_ts=ts,
                    demand=10.0 + k,
                    idle_supply=5.0,
                    effective_supply=0.0 if zero else 8.0,
                    observed_ds=None if zero else (10.0 + k) / 8.0,
                    surge_base=BASE[h],
                    null_reasons={"observed_ds": "ZERO_EFFECTIVE_SUPPLY"} if zero else {},
                )
            )
    session.flush()
    register_policy(session, policy)
    register_provider(session, _Fixed("0.1.0"))
    session.commit()

    set_s1 = _publish(session, ids[0], "0.1.0", S1_RECS)
    _publish(session, ids[1], "0.1.0", {"h1": ("INCREASE", "1.30"), "h2": ("HOLD", "1.50")})
    set_old = _publish(session, ids[2], "0.1.0", {"h1": ("INCREASE", "1.30")})
    set_new = _publish(session, ids[2], "0.2.0", {"h1": ("INCREASE", "1.35")})
    set_s4 = _publish(session, ids[3], "0.1.0", S4_RECS)

    def pid(set_id: str, hex_id: str) -> str:
        return session.scalar(
            select(Recommendation.proposal_id).where(
                Recommendation.recommendation_set_id == set_id, Recommendation.hex_id == hex_id
            )
        )

    return Seed(
        s1=ids[0],
        s2=ids[1],
        s3=ids[2],
        s4=ids[3],
        set_s4=set_s4,
        set_s1=set_s1,
        set_s3_old=set_old,
        set_s3_new=set_new,
        proposals={h: pid(set_s1, h) for h in HEXES},
        s3_old_h1=pid(set_old, "h1"),
        s3_new_h1=pid(set_new, "h1"),
    )
