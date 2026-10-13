"""Provider output validation (spec §4.5, §5.1 Layers A+B). Pure: no DB access.

Invalid recommendations are kept with validation_status=INVALID and their errors; they are never coerced
into a valid HOLD and can never be approved.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.core.config import Policy
from app.domain.enums import RecommendationAction, ValidationStatus
from app.domain.policies import consistency_errors, parse_decimal
from app.providers.base import OUTPUT_SCHEMA_VERSION, RecommendationBatch

_ACTIONS = {a.value for a in RecommendationAction}


@dataclass
class ValidatedRecommendation:
    provider_proposal_id: str | None
    hex_id: str
    action: str
    surge_base: Decimal | None
    surge_delta: Decimal | None
    surge_proposed: Decimal | None
    explanation: str
    reason_codes: list[str]
    evidence: dict[str, Any]
    validation_status: str
    validation_errors: list[str]


@dataclass
class ValidationReport:
    set_errors: list[str] = field(default_factory=list)
    rows: list[ValidatedRecommendation] = field(default_factory=list)
    rejected_rows: list[dict[str, Any]] = field(default_factory=list)  # unstorable (unknown hex/action, duplicates)

    @property
    def publishable(self) -> bool:
        return not self.set_errors

    def summary(self) -> dict[str, Any]:
        invalid = [r for r in self.rows if r.validation_status == ValidationStatus.INVALID]
        return {
            "set_errors": self.set_errors,
            "total": len(self.rows) + len(self.rejected_rows),
            "valid": len(self.rows) - len(invalid),
            "invalid": len(invalid),
            "rejected": self.rejected_rows,
        }


def json_safe(value):
    """Replace NaN/Infinity (not storable in JSONB) with None, recursively."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    return value


def _num(value, field_name: str, errors: list[str]) -> Decimal | None:
    try:
        return parse_decimal(value)
    except ValueError:
        errors.append(f"{field_name.upper()}_NOT_FINITE")
        return None


def validate_batch(
    batch: RecommendationBatch,
    *,
    snapshot_id: str,
    snapshot_hexes: set[str],
    dataset_fingerprint: str,
    policy: Policy,
) -> ValidationReport:
    report = ValidationReport()

    # Layer A — contract / set-level checks.
    if batch.schema_version != OUTPUT_SCHEMA_VERSION:
        report.set_errors.append("SCHEMA_VERSION_UNSUPPORTED")
    if not batch.provider.id or not batch.provider.version:
        report.set_errors.append("PROVIDER_IDENTITY_MISSING")
    if batch.snapshot_id != snapshot_id:
        report.set_errors.append("SNAPSHOT_MISMATCH")
    if batch.dataset_fingerprint and batch.dataset_fingerprint != dataset_fingerprint:
        report.set_errors.append("DATASET_FINGERPRINT_MISMATCH")
    if batch.policy_version != policy.policy_version:
        report.set_errors.append("POLICY_VERSION_CONFLICT")
    if not isinstance(batch.recommendations, list) or not batch.recommendations:
        report.set_errors.append("RECOMMENDATIONS_EMPTY")
        return report

    seen_hex: set[str] = set()
    seen_ids: set[str] = set()
    for raw in batch.recommendations:
        hex_id = raw.get("hex_id")
        action = raw.get("action")
        pid = raw.get("proposal_id")
        if not hex_id or hex_id not in snapshot_hexes:
            report.rejected_rows.append({"hex_id": hex_id, "proposal_id": pid, "error": "HEX_NOT_IN_SNAPSHOT"})
            continue
        if action not in _ACTIONS:
            report.rejected_rows.append({"hex_id": hex_id, "proposal_id": pid, "error": "ACTION_UNKNOWN"})
            continue
        if hex_id in seen_hex or (pid is not None and pid in seen_ids):
            report.rejected_rows.append({"hex_id": hex_id, "proposal_id": pid, "error": "DUPLICATE_PROPOSAL"})
            continue
        seen_hex.add(hex_id)
        if pid is not None:
            seen_ids.add(pid)

        errors: list[str] = []
        base = _num(raw.get("surge_base"), "surge_base", errors)
        delta = _num(raw.get("surge_delta"), "surge_delta", errors)
        proposed = _num(raw.get("surge_proposed"), "surge_proposed", errors)
        if not isinstance(raw.get("reason_codes", []), list):
            errors.append("REASON_CODES_INVALID")
        if base is not None and base <= 0:
            errors.append("SURGE_BASE_INVALID")
        if proposed is not None and proposed <= 0:
            errors.append("SURGE_PROPOSED_INVALID")
        # Layer B — action/surge consistency.
        if not errors:
            errors.extend(consistency_errors(action, base, delta, proposed))
        if delta is None and base is not None and proposed is not None and not errors:
            delta = proposed - base

        report.rows.append(
            ValidatedRecommendation(
                provider_proposal_id=pid,
                hex_id=hex_id,
                action=action,
                surge_base=base,
                surge_delta=delta,
                surge_proposed=proposed,
                explanation=str(raw.get("explanation") or ""),
                reason_codes=[str(c) for c in raw.get("reason_codes") or []]
                if isinstance(raw.get("reason_codes", []), list)
                else [],
                evidence=json_safe(raw.get("evidence")) if isinstance(raw.get("evidence"), dict) else {},
                validation_status=ValidationStatus.INVALID if errors else ValidationStatus.VALID,
                validation_errors=errors,
            )
        )
    return report
