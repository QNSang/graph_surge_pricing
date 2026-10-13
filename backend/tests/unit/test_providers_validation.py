import json
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.core.config import get_policy
from app.providers.base import OUTPUT_SCHEMA_VERSION, HexInput, ProviderInfo, RecommendationBatch, SnapshotInput
from app.providers.mock_provider import MockProvider
from app.providers.precomputed_provider import PrecomputedProvider
from app.services.validation_service import validate_batch

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
CUTOFF = datetime(2026, 1, 5, 8, 0, tzinfo=TZ)


@pytest.fixture
def policy():
    return get_policy()


def _snap(policy, hexes):
    return SnapshotInput(
        snapshot_id="snap_x",
        dataset_id="ds",
        dataset_fingerprint="fp",
        region_id="hcmc",
        cutoff_ts=CUTOFF,
        policy_version=policy.policy_version,
        hexes=tuple(hexes),
    )


def _hex(hid, ds, base="1.20", neighbors=()):
    return HexInput(hid, tuple(neighbors), 10.0, 5.0, 8.0, ds, base)


def _validate(policy, batch, hexes):
    return validate_batch(
        batch, snapshot_id="snap_x", snapshot_hexes=set(hexes), dataset_fingerprint="fp", policy=policy
    )


def test_mock_provider_output_is_valid_and_consistent(policy):
    provider = MockProvider(policy.mock_controller, policy.limits.precision)
    hexes = [
        _hex("a", 2.5, neighbors=("b",)),  # high pressure
        _hex("b", 2.4, neighbors=("a",)),
        _hex("c", 0.2, base="1.50", neighbors=("d",)),  # low pressure
        _hex("d", 0.3, base="1.50", neighbors=("c",)),
        _hex("e", 1.2),  # dead zone
        _hex("f", 0.0),  # q_local below q_min
        _hex("g", None),  # no observation
    ]
    batch = provider.generate(_snap(policy, hexes))
    report = _validate(policy, batch, [h.hex_id for h in hexes])
    assert report.publishable
    assert all(r.validation_status == "VALID" for r in report.rows), [r.validation_errors for r in report.rows]
    actions = {r.hex_id: r.action for r in report.rows}
    assert actions["a"] == "INCREASE" and actions["c"] == "DECREASE" and actions["e"] == "HOLD"
    assert actions["f"] == "REVIEW" and actions["g"] == "REVIEW"
    for r in report.rows:
        if r.surge_proposed is not None:
            assert r.surge_proposed == r.surge_proposed.quantize(Decimal("0.01"))
            assert abs(r.surge_proposed - r.surge_base) <= policy.limits.max_deviation


def _batch(policy, recs, **kw):
    args = dict(
        schema_version=OUTPUT_SCHEMA_VERSION,
        snapshot_id="snap_x",
        provider=ProviderInfo("p", "1", "MOCK"),
        policy_version=policy.policy_version,
        generated_at=datetime.now(UTC),
        recommendations=recs,
        dataset_fingerprint="fp",
    )
    args.update(kw)
    return RecommendationBatch(**args)


def test_validation_marks_invalid_rows_without_coercion(policy):
    recs = [
        {"hex_id": "a", "action": "INCREASE", "surge_base": "1.20", "surge_proposed": "1.10"},
        {"hex_id": "b", "action": "HOLD", "surge_base": "1.20", "surge_proposed": "NaN"},
        {"hex_id": "c", "action": "DECREASE", "surge_base": "1.20", "surge_proposed": "1.10"},
        {"hex_id": "c", "action": "DECREASE", "surge_base": "1.20", "surge_proposed": "1.10"},
        {"hex_id": "zz", "action": "HOLD", "surge_base": "1.20", "surge_proposed": "1.20"},
        {"hex_id": "d", "action": "JUMP", "surge_base": "1.20"},
    ]
    report = _validate(policy, _batch(policy, recs), ["a", "b", "c", "d"])
    rows = {r.hex_id: r for r in report.rows}
    assert rows["a"].validation_status == "INVALID" and rows["a"].action == "INCREASE"
    assert "SURGE_PROPOSED_NOT_FINITE" in rows["b"].validation_errors
    assert rows["c"].validation_status == "VALID" and rows["c"].surge_delta == Decimal("-0.10")
    errors = sorted(r["error"] for r in report.rejected_rows)
    assert errors == ["ACTION_UNKNOWN", "DUPLICATE_PROPOSAL", "HEX_NOT_IN_SNAPSHOT"]


@pytest.mark.parametrize(
    "kw,code",
    [
        ({"schema_version": "x"}, "SCHEMA_VERSION_UNSUPPORTED"),
        ({"snapshot_id": "other"}, "SNAPSHOT_MISMATCH"),
        ({"dataset_fingerprint": "other"}, "DATASET_FINGERPRINT_MISMATCH"),
        ({"policy_version": "other"}, "POLICY_VERSION_CONFLICT"),
        ({"recommendations": []}, "RECOMMENDATIONS_EMPTY"),
    ],
)
def test_set_level_rejection(policy, kw, code):
    recs = [{"hex_id": "a", "action": "HOLD", "surge_base": "1.20", "surge_proposed": "1.20"}]
    report = _validate(policy, _batch(policy, recs, **kw), ["a"])
    assert code in report.set_errors and not report.publishable


def test_precomputed_provider_maps_fixture(tmp_path, policy):
    payload = {
        "schema_version": "surge_proposal_v1",
        "cutoff_ts_local": "2026-01-05T08:00:00",
        "source_timezone": "Asia/Ho_Chi_Minh",
        "study_id": "s",
        "variant": "v",
        "seed": 1,
        "data_fingerprint": "fp",
        "policy_version": policy.policy_version,
        "proposals": [
            {"hex_id": "a", "status": "INCREASE", "bidding": 1.2, "final_surge": 1.4, "delta_requested": 0.2,
             "delta_applied": 0.2, "reason": "PRESSURE_REVISION", "q_local": 2.0, "q_graph": 2.1},
            {"hex_id": "b", "status": "REVIEW", "bidding": 1.2, "final_surge": float("nan"), "reason": "NONFINITE_FORECAST"},
        ],
    }
    (tmp_path / "proposals_k1.json").write_text(json.dumps(payload), encoding="utf-8")
    provider = PrecomputedProvider(tmp_path, policy.limits.precision)
    batch = provider.generate(_snap(policy, [_hex("a", 2.0), _hex("b", 1.0)]))
    report = _validate(policy, batch, ["a", "b"])
    rows = {r.hex_id: r for r in report.rows}
    assert rows["a"].action == "INCREASE" and rows["a"].surge_proposed == Decimal("1.40")
    assert rows["a"].reason_codes == ["PRESSURE_REVISION"]
    assert rows["b"].action == "REVIEW"
