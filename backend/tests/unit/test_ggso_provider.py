"""GGSO bridge tests use a frozen synthetic CLI artifact; no DB/model import."""
from __future__ import annotations
import ast
import copy
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import pytest
from app.core.config import Policy, SurgeLimits
from app.domain.policies import check_surge_value
from app.providers.base import HexInput, SnapshotInput
from app.providers.ggso_provider import GGSOProvider, GGSOProviderError, adapt_ggso_result
from app.services.validation_service import validate_batch

ARTIFACT = Path(__file__).resolve().parents[1] / "fixtures" / "ggso_decision.synthetic.json"


@pytest.fixture
def ggso_payload():
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


@pytest.fixture
def ggso_policy():
    return Policy(policy_version="test-backend-policy-v1", execution_mode="DEMO", replay_mode="DEMO_REPLAY",
                  region_id="TEST", region_label="TEST_ONLY", limits=SurgeLimits(min=Decimal("1.0"), max=Decimal("2.0"),
                  max_deviation=Decimal("0.4"), step=Decimal("0.01"), precision=2), override_requires_reason=True,
                  allow_hold_override=True, batch_plan_ttl_minutes=5, mock_controller={})


@pytest.fixture
def ggso_snapshot(ggso_payload, ggso_policy):
    identity = ggso_payload["identity"]
    return SnapshotInput(snapshot_id=identity["snapshot_id"], dataset_id=identity["dataset_id"],
        dataset_fingerprint=identity["dataset_fingerprint"], region_id="TEST",
        cutoff_ts=datetime.fromisoformat(identity["cutoff_time"].replace("Z", "+00:00")), policy_version=ggso_policy.policy_version,
        hexes=tuple(HexInput(hex_id=r["hex_id"], neighbors=(), demand=None, idle_supply=None,
                             effective_supply=None, observed_ds=None, surge_base=r["surge_base"])
                    for r in ggso_payload["recommendations"]))


def adapt(payload, snapshot, policy):
    return adapt_ggso_result(payload, snapshot=snapshot, policy=policy,
                             expected_reference_policy_version="test-effective-price-v1")


def test_ggso_full_synthetic_artifact_passes_legacy_validation(ggso_payload, ggso_snapshot, ggso_policy):
    batch = adapt(ggso_payload, ggso_snapshot, ggso_policy)
    report = validate_batch(batch, snapshot_id=ggso_snapshot.snapshot_id,
        snapshot_hexes={r.hex_id for r in ggso_snapshot.hexes}, dataset_fingerprint=ggso_snapshot.dataset_fingerprint,
        policy=ggso_policy)
    assert report.publishable and not report.rejected_rows
    assert len(report.rows) == len(ggso_snapshot.hexes)
    assert all(r.validation_status == "VALID" for r in report.rows)
    assert batch.schema_version == "recommendation.v1"
    assert batch.model_metadata["deployment_eligible"] is False
    assert batch.model_metadata["applied_vector_certified"] is False
    assert all("Pressure" not in r["evidence"] and "Revision" not in r["evidence"] for r in batch.recommendations)


def test_ggso_file_provider_records_source_hash(ggso_snapshot, ggso_policy):
    provider = GGSOProvider(ARTIFACT, ggso_policy, reference_policy_version="test-effective-price-v1")
    batch = provider.generate(ggso_snapshot)
    assert len(batch.model_metadata["source_sha256"]) == 64
    assert len(batch.recommendations) == len(ggso_snapshot.hexes)


@pytest.mark.parametrize("fault", ["invalid", "partial", "duplicate", "unknown_node", "wrong_fingerprint", "wrong_version",
    "production", "effective", "missing_validation", "corrupt_price", "corrupt_delta", "corrupt_vector",
    "stale_reference", "not_test_only", "wrong_time", "no_incumbent"])
def test_ggso_bridge_rejects_entire_policy(ggso_payload, ggso_snapshot, ggso_policy, fault):
    payload = copy.deepcopy(ggso_payload)
    if fault == "invalid":
        payload.update(result_status="INVALID", error_code="TEST_FAILURE", recommendations=[], selected_candidates=[],
                       optimized_policy=None, estimated_metrics=None, constraint_checks=None)
    elif fault == "partial": payload["recommendations"].pop()
    elif fault == "duplicate": payload["recommendations"][1] = payload["recommendations"][0]
    elif fault == "unknown_node": payload["selected_candidates"][0]["hex_id"] = "unknown"
    elif fault == "wrong_fingerprint": payload["identity"]["dataset_fingerprint"] = "other"
    elif fault == "wrong_version": payload["identity"]["reference_policy_version"] = "stale"
    elif fault == "production": payload["production_eligible"] = True
    elif fault == "effective": payload["production_effective"] = True
    elif fault == "missing_validation": payload["constraint_checks"]["nominal_no_loss"] = False
    elif fault == "corrupt_price": payload["recommendations"][0]["surge_proposed"] = "1.99"
    elif fault == "corrupt_delta": payload["selected_candidates"][0]["action"] = "0.01"
    elif fault == "corrupt_vector": payload["optimized_policy"][ggso_snapshot.hexes[0].hex_id] = "1.99"
    elif fault == "stale_reference":
        ggso_snapshot = replace(ggso_snapshot, hexes=tuple(replace(row, surge_base="1.23") for row in ggso_snapshot.hexes))
    elif fault == "not_test_only": payload["usage"] = "SHADOW"
    elif fault == "wrong_time": payload["identity"]["target_time"] = payload["identity"]["cutoff_time"]
    elif fault == "no_incumbent": payload["solver"]["accepted_status"] = "REJECTED"
    with pytest.raises(ValueError):
        adapt(payload, ggso_snapshot, ggso_policy)


def test_ggso_bridge_refuses_live_policy(ggso_payload, ggso_snapshot, ggso_policy):
    with pytest.raises(GGSOProviderError, match="live pricing"):
        adapt(ggso_payload, ggso_snapshot, replace(ggso_policy, execution_mode="LIVE"))


def test_manual_price_can_be_off_automatic_grid_without_running_milp(ggso_policy):
    # Existing backend manual policy is deliberately distinct from GGSO's 0.1 action grid.
    check_surge_value(Decimal("1.23"), Decimal("1.2"), ggso_policy.limits, {})


def test_bridge_preserves_backend_import_boundary():
    import app.providers.ggso_provider as module
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom): imported.append(node.module or "")
    assert not any(name.split(".")[0] in {"surge_ml", "torch", "scipy"} for name in imported)
