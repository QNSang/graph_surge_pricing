"""Explicit TEST_ONLY GGSO JSON -> legacy DEMO provider bridge.

Not registered automatically and never imports surge_ml/torch/scipy. This checks
transport identity and backend per-price limits; the producer's network certificate
applies only to its original optimized vector, NOT partial/manual execution.
"""
from __future__ import annotations
import hashlib
import json
import math
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from app.core.config import Policy
from app.domain.policies import check_surge_value, consistency_errors, parse_decimal
from app.providers.base import OUTPUT_SCHEMA_VERSION, ProviderInfo, RecommendationBatch, SnapshotInput


class GGSOProviderError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GGSOProviderError("GGSO_IMPORT_REJECTED", message)


def _time(value: Any) -> datetime:
    _require(isinstance(value, str), "Timestamp must be an aware ISO string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None, "Naive GGSO timestamp")
    return parsed


def _price(value: Any) -> Decimal:
    _require(isinstance(value, str), "GGSO prices must remain decimal strings")
    parsed = parse_decimal(value)
    _require(parsed is not None, "Missing price")
    return parsed


def _finite(value: Any) -> float:
    _require(not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value),
             "Missing/nonfinite GGSO numerical evidence")
    return float(value)


def adapt_ggso_result(payload: dict, *, snapshot: SnapshotInput, policy: Policy,
                      expected_reference_policy_version: str) -> RecommendationBatch:
    _require(policy.execution_mode == "DEMO", "This GGSO bridge cannot be activated in live pricing mode")
    _require(payload.get("schema_version") == "ggso.decision.v1", "Unsupported GGSO schema")
    _require(payload.get("usage") == "TEST_ONLY" and payload.get("production_eligible") is False
             and payload.get("production_effective") is False and payload.get("applied_vector_certified") is False,
             "Missing TEST_ONLY execution boundary")
    _require(payload.get("publication") == "NOT_REQUESTED", "Unexpected publication state")
    if payload.get("result_status") != "VALID":
        raise GGSOProviderError("GGSO_NO_RECOMMENDATION", "Technical INVALID has no importable recommendations")
    _require(payload.get("error_code") is None, "VALID result contains an error")
    identity = payload.get("identity") or {}
    nodes = [row.hex_id for row in snapshot.hexes]
    _require(bool(nodes) and len(set(nodes)) == len(nodes), "Invalid backend snapshot nodes")
    _require(identity.get("usage") == "TEST_ONLY" and identity.get("required_hex_ids") == nodes,
             "GGSO required node order differs from frozen backend snapshot")
    _require(identity.get("snapshot_id") == snapshot.snapshot_id
             and identity.get("dataset_id") == snapshot.dataset_id
             and identity.get("dataset_fingerprint") == snapshot.dataset_fingerprint,
             "GGSO snapshot/dataset fingerprint mismatch")
    _require(bool(expected_reference_policy_version)
             and identity.get("reference_policy_version") == expected_reference_policy_version,
             "Stale/mismatched effective price reference version")
    _require(snapshot.policy_version == policy.policy_version, "Backend execution policy is stale")
    cutoff = _time(identity.get("cutoff_time"))
    target = _time(identity.get("target_time"))
    generated = _time(payload.get("generated_at"))
    _require(cutoff == snapshot.cutoff_ts and target - cutoff == timedelta(minutes=5) and generated >= cutoff,
             "GGSO temporal identity mismatch")
    _require(identity.get("semantic_profile_id") == "ggso.confirmed-bookings.eligible-idle.h5.test.v1",
             "Unverified real or legacy semantic profile")
    checks = payload.get("constraint_checks") or {}
    _require(checks.get("validator_version") == "ggso.independent.v1" and
             all(checks.get(key) is True for key in ("coverage", "identity", "grid_and_bounds", "candidate_recomputed",
                                                    "booking_rate", "nominal_no_loss", "integrality")),
             "Missing full-network independent-validation evidence")
    solver = payload.get("solver") or {}
    _require(solver.get("accepted_status") in ("OPTIMAL", "FEASIBLE_LIMIT", "FEASIBLE_GAP"), "No accepted solver result")
    recommendations, candidates, vector = (payload.get("recommendations"), payload.get("selected_candidates"),
                                          payload.get("optimized_policy"))
    _require(isinstance(recommendations, list) and isinstance(candidates, list) and isinstance(vector, dict),
             "Missing GGSO output collections")
    _require([r.get("hex_id") for r in recommendations] == nodes and [c.get("hex_id") for c in candidates] == nodes
             and set(vector) == set(nodes), "Partial/duplicate/extra GGSO policy is not importable")
    ids = [c.get("candidate_id") for c in candidates]
    _require(all(isinstance(key, str) and key for key in ids) and len(set(ids)) == len(ids), "Duplicate/missing candidate IDs")
    output = []
    for source, candidate, backend_hex in zip(recommendations, candidates, snapshot.hexes):
        hex_id = backend_hex.hex_id
        action = source.get("action")
        base, delta, proposed = _price(source.get("surge_base")), _price(source.get("surge_delta")), _price(source.get("surge_proposed"))
        _require(action in ("INCREASE", "DECREASE", "HOLD") and not consistency_errors(action, base, delta, proposed),
                 "GGSO action/price inconsistency; technical errors cannot become HOLD/REVIEW")
        _require(base > 0 and proposed > 0 and base == _price(backend_hex.surge_base), "Reference prices no longer match")
        _require(abs(delta) <= Decimal("0.3") and delta % Decimal("0.1") == 0, "GGSO additive grid mismatch")
        _require(source.get("candidate_id") == candidate.get("candidate_id")
                 and _price(candidate.get("action")) == delta and _price(candidate.get("proposed_surge")) == proposed
                 and _price(vector[hex_id]) == proposed and candidate.get("decision_id") == identity.get("decision_id")
                 and candidate.get("snapshot_id") == snapshot.snapshot_id, "Selected candidate/policy identity mismatch")
        check_surge_value(proposed, base, policy.limits, {"hex_id": hex_id})
        outcome = candidate.get("outcome") or {}
        demand, completed, gmv, fulfillment = (_finite(outcome.get(key)) for key in
                                               ("expected_demand", "expected_completed", "expected_gmv", "fulfillment_rate"))
        _require(0 <= completed <= demand and gmv >= 0 and 0 <= fulfillment <= 1, "Invalid candidate outcomes")
        incremental, conservative = _finite(candidate.get("incremental_gmv")), _finite(candidate.get("conservative_utility"))
        output.append({"proposal_id": f"ggso_{candidate['candidate_id']}", "hex_id": hex_id, "action": action,
            "surge_base": str(base), "surge_delta": str(delta), "surge_proposed": str(proposed),
            "explanation": "TEST_ONLY GGSO validated full-network proposal; not an effective price.",
            "reason_codes": ["GGSO_VALIDATED_NETWORK_TEST_ONLY"],
            "evidence": {"ggso_decision_id": identity.get("decision_id"), "candidate_id": candidate["candidate_id"],
                "expected_demand": demand, "expected_completed": completed, "expected_gmv": gmv,
                "nominal_incremental_gmv": incremental, "conservative_utility": conservative,
                "network_certificate_scope": "FULL_OPTIMIZED_VECTOR_ONLY", "applied_vector_certified": False}})
    return RecommendationBatch(schema_version=OUTPUT_SCHEMA_VERSION, snapshot_id=snapshot.snapshot_id,
        provider=ProviderInfo(id="ggso_test_only", version="ggso-demo-adapter.v1", kind="precomputed"),
        policy_version=policy.policy_version, generated_at=generated, recommendations=output,
        dataset_fingerprint=snapshot.dataset_fingerprint,
        model_metadata={"source_schema": "ggso.decision.v1", "usage": "TEST_ONLY", "deployment_eligible": False,
            "forecast_version": payload.get("forecast_version"), "response_version": payload.get("response_version"),
            "ggso_policy_config_version": payload.get("policy_config_version"),
            "reference_policy_version": expected_reference_policy_version,
            "network_certificate_scope": "FULL_OPTIMIZED_VECTOR_ONLY", "applied_vector_certified": False,
            "publication": "NOT_REQUESTED"})


class GGSOProvider:
    """Explicit opt-in bridge. Existing provider registry/import routes are unchanged."""
    info = ProviderInfo(id="ggso_test_only", version="ggso-demo-adapter.v1", kind="precomputed")

    def __init__(self, source: Path, policy: Policy, *, reference_policy_version: str):
        self.source, self.policy = Path(source), policy
        self.reference_policy_version = reference_policy_version

    def generate(self, snapshot: SnapshotInput) -> RecommendationBatch:
        content = self.source.read_bytes()
        payload = json.loads(content)
        _require(isinstance(payload, dict), "GGSO source must be a JSON object")
        batch = adapt_ggso_result(payload, snapshot=snapshot, policy=self.policy,
                                  expected_reference_policy_version=self.reference_policy_version)
        batch.model_metadata["source_sha256"] = hashlib.sha256(content).hexdigest()
        return batch
