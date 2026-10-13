"""Spec §15.4 end-to-end flow through the HTTP API."""

from __future__ import annotations

import hashlib
import json
import uuid

import pytest
from sqlalchemy import text

from tests.conftest import OPERATOR, VIEWER

pytestmark = pytest.mark.integration

API = "/api/v1"


def _market_hash(db, snapshot_id):
    rows = db.execute(
        text("SELECT hex_id, demand, idle_supply, effective_supply, observed_ds, surge_base, null_reasons "
             "FROM hex_market_states WHERE snapshot_id = :s ORDER BY hex_id"),
        {"s": snapshot_id},
    ).all()
    return hashlib.sha256(json.dumps([list(map(str, r)) for r in rows]).encode()).hexdigest()


def test_full_demo_flow(client, seeded, db):
    source_before = _market_hash(db, seeded.s4)

    # 1. Create demo session.
    r = client.post(f"{API}/demo-sessions", headers=OPERATOR, json={"name": "e2e"})
    assert r.status_code == 201
    ds = r.json()["demo_session_id"]

    # 2. Load snapshot.
    snap = client.get(f"{API}/snapshots/{seeded.s4}", headers=VIEWER).json()
    assert snap["snapshot_id"] == seeded.s4

    # 3. Load recommendations (one read-model identity for map + queue + panel).
    rm = client.get(f"{API}/snapshots/{seeded.s4}/read-model?demo_session_id={ds}", headers=OPERATOR).json()
    assert rm["recommendation_set"]["recommendation_set_id"] == seeded.set_s4
    by_hex = {h["hex_id"]: h["proposal"] for h in rm["hexes"]}

    # 4. Select hex.
    detail = client.get(f"{API}/recommendations/{by_hex['h1']['proposal_id']}?demo_session_id={ds}", headers=OPERATOR).json()
    assert detail["capabilities"]["accept"] is True

    def decide(hex_id, action, **extra):
        p = by_hex[hex_id]
        return client.post(
            f"{API}/decisions",
            headers=OPERATOR,
            json={
                "demo_session_id": ds,
                "idempotency_key": str(uuid.uuid4()),
                "proposal_id": p["proposal_id"],
                "expected_proposal_version": p["proposal_version"],
                "snapshot_id": seeded.s4,
                "recommendation_set_id": seeded.set_s4,
                "expected_policy_version": rm["policy"]["policy_version"],
                "action": action,
                **extra,
            },
        )

    # 5. Accept recommendation.
    accepted = decide("h1", "ACCEPT_PROPOSAL")
    assert accepted.status_code == 201 and accepted.json()["surge_decided"] == "1.40"
    # 6. Manual edit another hex.
    edited = decide("h3", "OVERRIDE_PROPOSAL", requested_surge="1.10", reason="Event nearby")
    assert edited.status_code == 201 and edited.json()["surge_decided"] == "1.10"
    # 7. Keep base on another hex.
    kept = decide("h2", "KEEP_BIDDING")
    assert kept.status_code == 201 and kept.json()["status"] == "KEPT_BIDDING"

    # 8. Preview Accept All: only undecided, eligible INCREASE/DECREASE proposals.
    prev = client.post(
        f"{API}/batches/preview",
        headers=OPERATOR,
        json={"demo_session_id": ds, "snapshot_id": seeded.s4, "recommendation_set_id": seeded.set_s4,
              "selection_mode": "ALL_ELIGIBLE", "proposal_ids": []},
    ).json()
    assert {i["hex_id"] for i in prev["items"] if i["eligible"]} == {"h5", "h6"}

    # 9. Commit batch.
    res = client.post(
        f"{API}/decisions/batch",
        headers=OPERATOR,
        json={"demo_session_id": ds, "batch_plan_id": prev["batch_plan_id"], "idempotency_key": str(uuid.uuid4())},
    ).json()
    assert res["status"] == "SUCCESS" and res["succeeded"] == 2 and res["production_effective"] is False

    # 10. Review batch results.
    batch = client.get(f"{API}/batches/{res['batch_id']}", headers=VIEWER).json()
    assert all(r["decision_id"] for r in batch["results"])

    # 11. Query decision history.
    hist = client.get(f"{API}/demo-sessions/{ds}/decisions", headers=VIEWER).json()["items"]
    assert len(hist) == 5
    assert sum(1 for d in hist if d["batch_id"] == res["batch_id"]) == 2

    # 12. Query audit.
    audit = client.get(f"{API}/audit-events?demo_session_id={ds}&limit=50", headers=VIEWER).json()["items"]
    actions = [e["action"] for e in audit]
    for expected in ("DEMO_SESSION_CREATED", "DECISION_ACCEPT_PROPOSAL", "DECISION_OVERRIDE_PROPOSAL",
                     "DECISION_KEEP_BIDDING", "BATCH_PREVIEWED", "BATCH_COMPLETED"):
        assert expected in actions

    # 13. Replay snapshot: every movable proposal now carries the session's decision.
    replay = client.get(f"{API}/snapshots/{seeded.s4}/read-model?demo_session_id={ds}", headers=VIEWER).json()
    assert replay["summary"]["accept_all_candidates"] == 0
    assert replay["summary"]["by_decision_status"].get("UNDECIDED") == 1  # only the REVIEW hex
    bidding = client.get(f"{API}/hexes/h1/history?series=BASE_BIDDING", headers=VIEWER).json()
    assert all(p["value"] in (None, "1.20") for p in bidding["points"])

    # 14. Source data unchanged.
    db.expire_all()
    assert _market_hash(db, seeded.s4) == source_before
