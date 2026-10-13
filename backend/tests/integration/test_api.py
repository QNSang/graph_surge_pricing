"""Integration tests against PostgreSQL. Test ids follow spec Â§15 (BE-01 â€¦ BE-24)."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.api.deps import policy_dep
from app.core.config import get_policy
from app.core.errors import AppError
from app.core.security import parse_tokens
from app.db.models import Decision, Recommendation, RecommendationSet
from app.db.session import get_sessionmaker
from app.main import app
from app.services import batch_service, decision_service
from tests.conftest import OPERATOR, VIEWER
from tests.fixtures import seed as seed_mod

pytestmark = pytest.mark.integration

API = "/api/v1"


def decision_body(seeded, demo_session, hex_id="h1", action="ACCEPT_PROPOSAL", **extra):
    return {
        "schema_version": "surge-decision.v1",
        "demo_session_id": demo_session,
        "idempotency_key": str(uuid.uuid4()),
        "proposal_id": seeded.proposals[hex_id],
        "expected_proposal_version": "1",
        "snapshot_id": seeded.s1,
        "recommendation_set_id": seeded.set_s1,
        "action": action,
        **extra,
    }


def post_decision(client, body, headers=OPERATOR):
    return client.post(f"{API}/decisions", headers=headers, json=body)


def code(resp):
    return resp.json()["error"]["code"]


# --- provider output / validation (BE-01..03, BE-19) ---------------------------------------------------------


def test_be01_be02_valid_and_inconsistent_proposals(client, seeded):
    items = client.get(f"{API}/snapshots/{seeded.s1}/recommendations", headers=VIEWER).json()["items"]
    by_hex = {i["hex_id"]: i for i in items}
    assert by_hex["h1"]["action"] == "INCREASE" and by_hex["h1"]["eligibility"]["state"] == "ELIGIBLE"
    assert by_hex["h1"]["surge_proposed"] == "1.40" and by_hex["h1"]["surge_delta"] == "0.20"
    # Inconsistent action/price is stored as-is (never coerced to HOLD) and blocked.
    assert by_hex["h5"]["action"] == "INCREASE"
    assert by_hex["h5"]["validation"]["status"] == "INVALID"
    assert by_hex["h5"]["eligibility"]["state"] == "BLOCKED"
    assert not any(by_hex["h5"]["capabilities"].values())
    assert by_hex["h6"]["eligibility"]["reasons"] == ["SURGE_LIMIT_EXCEEDED"]


def test_be03_non_finite_never_published_valid(db, seeded):
    policy = get_policy()
    batch = seed_mod._batch(seeded.s2, "nan-test", {"h1": ("INCREASE", "NaN")}, policy.policy_version)
    report = seed_mod.validate_batch(
        batch, snapshot_id=seeded.s2, snapshot_hexes=set(seed_mod.HEXES), dataset_fingerprint=seed_mod.FINGERPRINT, policy=policy
    )
    assert report.rows[0].validation_status == "INVALID"
    assert "SURGE_PROPOSED_NOT_FINITE" in report.rows[0].validation_errors


def test_be19_new_provider_same_contract_same_api_shape(client, seeded):
    a = client.get(f"{API}/snapshots/{seeded.s1}/recommendations", headers=VIEWER).json()["items"][0]
    b = client.get(f"{API}/snapshots/{seeded.s3}/recommendations", headers=VIEWER).json()["items"][0]
    assert set(a) == set(b)
    assert b["provider"]["version"] == "0.2.0"


def test_superseded_set_is_not_decidable(client, seeded, demo_session):
    old = client.get(f"{API}/recommendations/{seeded.s3_old_h1}", headers=VIEWER).json()
    assert old["eligibility"]["state"] == "SUPERSEDED"
    body = decision_body(seeded, demo_session)
    body.update(proposal_id=seeded.s3_old_h1, snapshot_id=seeded.s3, recommendation_set_id=seeded.set_s3_old)
    r = post_decision(client, body)
    assert r.status_code == 409 and code(r) == "PROPOSAL_SUPERSEDED"


# --- single decisions (BE-04..08, BE-14, BE-15, BE-17, BE-20) ------------------------------------------------


def test_be04_accept_records_proposed(client, seeded, demo_session):
    r = post_decision(client, decision_body(seeded, demo_session, requested_surge="2.00"))
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "RECORDED" and d["surge_decided"] == "1.40"  # client surge ignored on accept
    assert d["requested_surge"] is None


def test_be05_keep_base(client, seeded, demo_session):
    r = post_decision(client, decision_body(seeded, demo_session, hex_id="h2", action="KEEP_BIDDING"))
    assert r.status_code == 201
    assert r.json()["status"] == "KEPT_BIDDING" and r.json()["surge_decided"] == "1.50"


def test_be06_override_valid(client, seeded, demo_session):
    r = post_decision(
        client, decision_body(seeded, demo_session, action="OVERRIDE_PROPOSAL", requested_surge="1.35", reason="ops call")
    )
    assert r.status_code == 201
    assert r.json()["surge_decided"] == "1.35" and r.json()["reason"] == "ops call"


def test_override_hold_allowed_by_policy(client, seeded, demo_session):
    r = post_decision(
        client, decision_body(seeded, demo_session, hex_id="h3", action="OVERRIDE_PROPOSAL", requested_surge="1.10", reason="x")
    )
    assert r.status_code == 201


@pytest.mark.parametrize(
    "extra,status,err",
    [
        ({"requested_surge": "1.70", "reason": "x"}, 422, "SURGE_LIMIT_EXCEEDED"),
        ({"requested_surge": "3.20", "reason": "x"}, 422, "SURGE_LIMIT_EXCEEDED"),
        ({"requested_surge": "1.333", "reason": "x"}, 422, "INVALID_SURGE_PRECISION"),
        ({"requested_surge": "1.30"}, 422, "REASON_REQUIRED"),
    ],
)
def test_be07_override_rejected(client, seeded, demo_session, extra, status, err):
    r = post_decision(client, decision_body(seeded, demo_session, action="OVERRIDE_PROPOSAL", **extra))
    assert r.status_code == status and code(r) == err


def test_be08_review_and_hold_rules(client, seeded, demo_session):
    r = post_decision(client, decision_body(seeded, demo_session, hex_id="h4"))
    assert code(r) == "REVIEW_REQUIRED"
    r = post_decision(client, decision_body(seeded, demo_session, hex_id="h3"))
    assert code(r) == "ACTION_NOT_ALLOWED"
    r = post_decision(client, decision_body(seeded, demo_session, hex_id="h5"))
    assert code(r) == "PROPOSAL_BLOCKED"


def test_be14_wrong_proposal_version(client, seeded, demo_session):
    r = post_decision(client, decision_body(seeded, demo_session, expected_proposal_version="2"))
    assert r.status_code == 409 and code(r) == "PROPOSAL_VERSION_CONFLICT"


def test_snapshot_and_set_mismatch(client, seeded, demo_session):
    assert code(post_decision(client, decision_body(seeded, demo_session, snapshot_id=seeded.s2))) == "SNAPSHOT_MISMATCH"
    r = post_decision(client, decision_body(seeded, demo_session, recommendation_set_id=seeded.set_s3_new))
    assert code(r) == "RECOMMENDATION_SET_MISMATCH"


def test_be15_policy_change_before_commit(client, seeded, demo_session):
    r = post_decision(client, decision_body(seeded, demo_session, expected_policy_version="old_policy"))
    assert r.status_code == 409 and code(r) == "POLICY_VERSION_CONFLICT"
    app.dependency_overrides[policy_dep] = lambda: replace(get_policy(), policy_version="policy_v2")
    try:
        r = post_decision(client, decision_body(seeded, demo_session))
    finally:
        app.dependency_overrides.pop(policy_dep)
    assert code(r) == "POLICY_VERSION_CONFLICT"


def test_be17_decision_persists_after_reload(client, seeded, demo_session):
    d = post_decision(client, decision_body(seeded, demo_session)).json()
    with TestClient(app) as fresh:
        got = fresh.get(f"{API}/decisions/{d['decision_id']}", headers=VIEWER).json()
        rm = fresh.get(f"{API}/snapshots/{seeded.s1}/read-model?demo_session_id={demo_session}", headers=VIEWER).json()
    assert got["decision_id"] == d["decision_id"]
    h1 = next(h for h in rm["hexes"] if h["hex_id"] == "h1")
    assert h1["proposal"]["decision"]["decision_id"] == d["decision_id"]
    assert not any(h1["proposal"]["capabilities"].values())


def test_be20_demo_only(client, seeded, demo_session, db):
    d = post_decision(client, decision_body(seeded, demo_session)).json()
    assert d["execution_mode"] == "DEMO" and d["production_effective"] is False
    with pytest.raises(Exception):
        db.execute(text("UPDATE decisions SET execution_mode = 'LIVE' WHERE decision_id = :d"), {"d": d["decision_id"]})
    db.rollback()


# --- idempotency & concurrency (BE-11..13, BE-18) -------------------------------------------------------------


def test_be11_retry_same_key_no_duplicate(client, seeded, demo_session, db):
    body = decision_body(seeded, demo_session)
    first = post_decision(client, body)
    second = post_decision(client, body)
    assert first.status_code == second.status_code == 201
    assert second.headers.get("Idempotent-Replayed") == "true"
    assert first.json()["decision_id"] == second.json()["decision_id"]
    n = db.scalar(select(func.count()).select_from(Decision).where(Decision.demo_session_id == uuid.UUID(demo_session)))
    assert n == 1
    looked = client.get(f"{API}/decisions/by-idempotency/{body['idempotency_key']}", headers=OPERATOR).json()
    assert looked["resource_id"] == first.json()["decision_id"]


def test_be12_same_key_different_payload(client, seeded, demo_session):
    body = decision_body(seeded, demo_session)
    assert post_decision(client, body).status_code == 201
    r = post_decision(client, {**body, "action": "KEEP_BIDDING"})
    assert r.status_code == 409 and code(r) == "IDEMPOTENCY_CONFLICT"


def test_duplicate_final_decision(client, seeded, demo_session):
    assert post_decision(client, decision_body(seeded, demo_session)).status_code == 201
    r = post_decision(client, decision_body(seeded, demo_session, action="KEEP_BIDDING"))
    assert r.status_code == 409 and code(r) == "DECISION_ALREADY_EXISTS"


def test_be13_concurrent_requests_one_final_decision(seeded, demo_session):
    actor = parse_tokens("t:operator_01:OPERATOR")["t"]
    policy = get_policy()
    barrier = threading.Barrier(4)
    outcomes: list[str] = []

    def worker():
        cmd = decision_service.DecisionCommand(
            demo_session_id=uuid.UUID(demo_session),
            idempotency_key=str(uuid.uuid4()),
            proposal_id=seeded.proposals["h1"],
            expected_proposal_version="1",
            snapshot_id=seeded.s1,
            action="ACCEPT_PROPOSAL",
        )
        with get_sessionmaker()() as s:
            barrier.wait()
            try:
                decision_service.record(s, actor, cmd, policy, correlation_id=None)
                outcomes.append("ok")
            except AppError as err:
                outcomes.append(err.code)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("ok") == 1
    assert set(outcomes) - {"ok"} == {"DECISION_ALREADY_EXISTS"}


def test_be18_audit_failure_rolls_back_decision(seeded, demo_session, db, monkeypatch):
    from app.repositories import audit_repository

    def boom(*a, **kw):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(audit_repository, "append", boom)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = post_decision(c, decision_body(seeded, demo_session))
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    n = db.scalar(select(func.count()).select_from(Decision).where(Decision.demo_session_id == uuid.UUID(demo_session)))
    assert n == 0


# --- batch (BE-09, BE-10, BE-21, BE-23) ------------------------------------------------------------------------


def preview(client, seeded, demo_session, mode="ALL_ELIGIBLE", ids=(), snapshot=None, set_id=None):
    return client.post(
        f"{API}/batches/preview",
        headers=OPERATOR,
        json={
            "demo_session_id": demo_session,
            "snapshot_id": snapshot or seeded.s1,
            "recommendation_set_id": set_id or seeded.set_s1,
            "selection_mode": mode,
            "proposal_ids": list(ids),
        },
    )


def commit(client, demo_session, plan_id, key=None):
    return client.post(
        f"{API}/decisions/batch",
        headers=OPERATOR,
        json={"demo_session_id": demo_session, "batch_plan_id": plan_id, "idempotency_key": key or str(uuid.uuid4())},
    )


def test_batch_preview_all_eligible(client, seeded, demo_session):
    p = preview(client, seeded, demo_session).json()
    eligible = {i["hex_id"] for i in p["items"] if i["eligible"]}
    assert eligible == {"h1", "h2"}
    skipped = {i["hex_id"]: i["reason_code"] for i in p["items"] if not i["eligible"]}
    assert skipped["h4"] == "REVIEW_REQUIRED" and skipped["h3"] == "HOLD_NO_ACTION"
    assert skipped["h5"] in ("VALIDATION_FAILED", "PROPOSAL_BLOCKED")


def test_be09_batch_across_snapshots_rejected(client, seeded, demo_session):
    r = preview(client, seeded, demo_session, mode="SELECTED", ids=[seeded.proposals["h1"], seeded.s3_new_h1])
    assert r.status_code in (409, 422) and code(r) in ("SNAPSHOT_MISMATCH", "RECOMMENDATION_SET_MISMATCH")


def test_be10_partial_success(client, seeded, demo_session):
    p = preview(client, seeded, demo_session, mode="SELECTED", ids=[seeded.proposals["h1"], seeded.proposals["h2"]]).json()
    assert p["eligible_count"] == 2
    # h2 gets decided individually after preview, so its batch item must fail.
    assert post_decision(client, decision_body(seeded, demo_session, hex_id="h2", action="KEEP_BIDDING")).status_code == 201
    key = str(uuid.uuid4())
    res = commit(client, demo_session, p["batch_plan_id"], key).json()
    assert res["status"] == "PARTIAL_SUCCESS" and res["succeeded"] == 1 and res["failed"] == 1
    failed = next(r for r in res["results"] if r["status"] == "FAILED")
    assert failed["error_code"] == "DECISION_ALREADY_EXISTS"
    again = commit(client, demo_session, p["batch_plan_id"], key)
    assert again.headers.get("Idempotent-Replayed") == "true" and again.json()["batch_id"] == res["batch_id"]
    assert client.get(f"{API}/batches/{res['batch_id']}", headers=VIEWER).json()["status"] == "PARTIAL_SUCCESS"


def test_be21_interrupted_batch_resumes_without_duplicates(client, seeded, demo_session, db, monkeypatch):
    p = preview(client, seeded, demo_session).json()
    real = batch_service._process_item
    calls = {"n": 0}

    def crash_after_first(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("worker died")
        return real(*args, **kwargs)

    monkeypatch.setattr(batch_service, "_process_item", crash_after_first)
    key = str(uuid.uuid4())
    with TestClient(app, raise_server_exceptions=False) as c:
        assert commit(c, demo_session, p["batch_plan_id"], key).status_code == 500
    monkeypatch.setattr(batch_service, "_process_item", real)

    res = commit(client, demo_session, p["batch_plan_id"], key).json()
    assert res["status"] == "SUCCESS" and res["succeeded"] == 2
    n = db.scalar(select(func.count()).select_from(Decision).where(Decision.demo_session_id == uuid.UUID(demo_session)))
    assert n == 2


def test_be23_new_proposals_after_preview_not_added(client, seeded, demo_session, db):
    p = preview(client, seeded, demo_session, snapshot=seeded.s2, set_id=_current_set(db, seeded.s2)).json()
    planned = {i["proposal_id"] for i in p["items"] if i["eligible"]}
    # A newer recommendation set appears for the same snapshot after the preview.
    seed_mod._publish(db, seeded.s2, f"late-{uuid.uuid4().hex[:6]}", {"h1": ("INCREASE", "1.25"), "h2": ("DECREASE", "1.45")})
    res = commit(client, demo_session, p["batch_plan_id"]).json()
    assert {r["proposal_id"] for r in res["results"]} == planned
    assert all(r["error_code"] == "PROPOSAL_SUPERSEDED" for r in res["results"])


def _current_set(db, snapshot_id):
    return db.scalar(
        select(RecommendationSet.recommendation_set_id)
        .where(RecommendationSet.snapshot_id == snapshot_id, RecommendationSet.status == "PUBLISHED")
        .order_by(RecommendationSet.created_at.desc())
        .limit(1)
    )


# --- replay / history (BE-16, BE-22) ---------------------------------------------------------------------------


def _market_hash(db, snapshot_id):
    rows = db.execute(
        text("SELECT hex_id, demand, effective_supply, observed_ds, surge_base FROM hex_market_states "
             "WHERE snapshot_id = :s ORDER BY hex_id"),
        {"s": snapshot_id},
    ).all()
    return hashlib.sha256(json.dumps([list(map(str, r)) for r in rows]).encode()).hexdigest()


def test_be16_replay_source_unchanged_by_decisions(client, seeded, demo_session, db):
    before = _market_hash(db, seeded.s1)
    post_decision(client, decision_body(seeded, demo_session, action="OVERRIDE_PROPOSAL", requested_surge="1.55", reason="x"))
    db.expire_all()
    assert _market_hash(db, seeded.s1) == before
    hist = client.get(f"{API}/hexes/h1/history?series=BASE_BIDDING", headers=VIEWER).json()
    assert hist["points"][0]["value"] == "1.20"


def test_be22_history_keeps_null_and_gap(client, seeded):
    hist = client.get(f"{API}/hexes/h4/history?series=OBSERVED_DS", headers=VIEWER).json()
    pts = hist["points"]
    assert pts[0]["value"] is None and pts[0]["reason"] == "ZERO_EFFECTIVE_SUPPLY"
    gaps = [p for p in pts if p.get("reason") == "NO_SNAPSHOT"]
    assert len(gaps) == 1 and gaps[0]["ts"].endswith("08:15:00+07:00")
    r = client.get(f"{API}/hexes/h4/history?series=FORECAST_DS", headers=VIEWER)
    assert r.status_code == 422 and code(r) == "SERIES_UNAVAILABLE"


# --- auth (BE-24) ----------------------------------------------------------------------------------------------


def test_be24_permissions(client, seeded, demo_session):
    assert client.get(f"{API}/snapshots").status_code == 401
    assert client.get(f"{API}/snapshots", headers={"Authorization": "Bearer nope"}).status_code == 401
    r = post_decision(client, decision_body(seeded, demo_session), headers=VIEWER)
    assert r.status_code == 403 and code(r) == "PERMISSION_DENIED"
    assert preview(client, seeded, demo_session).status_code == 201
    r = client.post(f"{API}/demo-sessions", headers=VIEWER, json={})
    assert r.status_code == 403


# --- read model / pagination -----------------------------------------------------------------------------------


def test_read_model_and_summary_consistent(client, seeded):
    rm = client.get(f"{API}/snapshots/{seeded.s1}/read-model", headers=VIEWER).json()
    assert rm["snapshot"]["snapshot_id"] == seeded.s1
    assert rm["recommendation_set"]["recommendation_set_id"] == seeded.set_s1
    assert len(rm["hexes"]) == len(seed_mod.HEXES)
    h4 = next(h for h in rm["hexes"] if h["hex_id"] == "h4")
    assert h4["market"]["observed_ds"] is None
    summary = client.get(f"{API}/snapshots/{seeded.s1}/summary", headers=VIEWER).json()
    assert summary["by_action"] == rm["summary"]["by_action"]
    assert summary["accept_all_candidates"] == 2


def test_snapshot_pagination_and_navigation(client, seeded):
    page1 = client.get(f"{API}/snapshots?limit=2", headers=VIEWER).json()
    page2 = client.get(f"{API}/snapshots?limit=2&cursor={page1['next_cursor']}", headers=VIEWER).json()
    ids = [s["snapshot_id"] for s in page1["items"] + page2["items"]]
    assert ids[:3] == [seeded.s1, seeded.s2, seeded.s3] and len(set(ids)) == len(ids)
    detail = client.get(f"{API}/snapshots/{seeded.s2}", headers=VIEWER).json()
    assert detail["navigation"]["previous_snapshot_id"] == seeded.s1
    assert detail["navigation"]["next_snapshot_id"] == seeded.s3
    assert client.get(f"{API}/snapshots?cursor=garbage", headers=VIEWER).status_code == 400


def test_recommendation_filters(client, seeded, demo_session):
    post_decision(client, decision_body(seeded, demo_session))
    base = f"{API}/snapshots/{seeded.s1}/recommendations"
    assert client.get(f"{base}?action=INCREASE", headers=VIEWER).json()["total"] == 3
    assert client.get(f"{base}?eligibility=BLOCKED", headers=VIEWER).json()["total"] == 2
    recorded = client.get(f"{base}?decision_status=RECORDED&demo_session_id={demo_session}", headers=VIEWER).json()
    assert [i["hex_id"] for i in recorded["items"]] == ["h1"]
    assert client.get(f"{base}?decision_status=RECORDED", headers=VIEWER).status_code == 400


def test_audit_trail(client, seeded, demo_session):
    d = post_decision(client, decision_body(seeded, demo_session)).json()
    events = client.get(f"{API}/audit-events?demo_session_id={demo_session}", headers=VIEWER).json()["items"]
    actions = [e["action"] for e in events]
    assert "DEMO_SESSION_CREATED" in actions and "DECISION_ACCEPT_PROPOSAL" in actions
    ev = next(e for e in events if e["action"] == "DECISION_ACCEPT_PROPOSAL")
    assert ev["entity_id"] == d["decision_id"] and ev["actor_id"] == "operator_01"
