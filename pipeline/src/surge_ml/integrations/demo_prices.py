"""TEST_ONLY in-memory operator/receipt boundary for GD-07.

Recording an intent does not change the reference. Only an explicit simulated
receipt transition does. No database, network, forecast or optimizer is imported.
This is not the production authorization/audit/price gateway implementation.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Annotated
from pydantic import Field, model_validator
from surge_ml.contracts import Adjustment, Name, OperationalSnapshot, Price, TestOnly
from surge_ml.errors import require


class ManualPolicy(TestOnly):
    version: Name
    surge_min: Price
    surge_max: Price
    max_deviation: Adjustment
    step: Price
    precision: Annotated[int, Field(strict=True, ge=0, le=6)]

    @model_validator(mode="after")
    def coherent(self):
        if self.surge_min >= self.surge_max or self.max_deviation < 0:
            raise ValueError("Invalid TEST_ONLY manual policy bounds")
        return self


@dataclass(frozen=True)
class DemoReceipt:
    receipt_id: str
    operator_id: str
    hex_id: str
    price: Decimal
    source_version: str
    reason: str
    status: str
    effective_reference_version: str | None = None
    usage: str = "TEST_ONLY"
    production_effective: bool = False


class DemoPriceBook:
    def __init__(self, snapshot: OperationalSnapshot, policy: ManualPolicy):
        snapshot = OperationalSnapshot.model_validate(snapshot)
        self.policy = ManualPolicy.model_validate(policy)
        self._prices = {r.hex_id: r.current_surge for r in snapshot.rows}
        self._initial_version = self._version = snapshot.identity.reference_policy_version
        self._receipts: dict[str, DemoReceipt] = {}
        self._keys: dict[str, tuple[tuple, str]] = {}
        self._audit: list[DemoReceipt] = []
        self._generation = 0

    def reference(self) -> tuple[str, dict[str, Decimal]]:
        return self._version, dict(self._prices)

    @property
    def audit(self) -> tuple[DemoReceipt, ...]:
        return tuple(self._audit)

    def record(self, *, operator_id: str, role: str, hex_id: str, price: str | Decimal,
               expected_reference_version: str, idempotency_key: str, reason: str) -> DemoReceipt:
        require(role == "OPERATOR" and bool(operator_id), "OPERATOR_DENIED", "Operator permission required")
        require(bool(idempotency_key) and bool(reason.strip()), "OPERATOR_INVALID", "Key and audit reason required")
        require(isinstance(price, (str, Decimal)), "OPERATOR_INVALID", "Canonical decimal manual price required")
        value = Decimal(price)
        require(value.is_finite(), "OPERATOR_INVALID", "Nonfinite manual price")
        fingerprint = (operator_id, hex_id, value, expected_reference_version, reason)
        if idempotency_key in self._keys:
            previous, receipt_id = self._keys[idempotency_key]
            require(previous == fingerprint, "IDEMPOTENCY_CONFLICT", "Same key used for a different intent")
            return self._receipts[receipt_id]
        require(expected_reference_version == self._version, "REFERENCE_CONFLICT", "Stale effective-price reference")
        require(hex_id in self._prices, "OPERATOR_INVALID", "Unknown cell")
        policy = self.policy
        require(policy.surge_min <= value <= policy.surge_max and abs(value - self._prices[hex_id]) <= policy.max_deviation
                and value % policy.step == 0 and value == value.quantize(Decimal(1).scaleb(-policy.precision)),
                "OPERATOR_INVALID", "Manual bounds/step/precision violation")
        receipt_id = f"test-receipt-{len(self._receipts) + 1:06d}"
        receipt = DemoReceipt(receipt_id, operator_id, hex_id, value, self._version, reason, "RECORDED")
        self._receipts[receipt_id] = receipt
        self._keys[idempotency_key] = fingerprint, receipt_id
        self._audit.append(receipt)
        return receipt

    def confirm_simulated_effective(self, receipt_ids: tuple[str, ...]) -> tuple[DemoReceipt, ...]:
        require(bool(receipt_ids) and len(set(receipt_ids)) == len(receipt_ids)
                and all(key in self._receipts for key in receipt_ids), "RECEIPT_INVALID", "Missing/duplicate receipt")
        receipts = tuple(self._receipts[key] for key in receipt_ids)
        if all(r.status == "SIMULATED_EFFECTIVE" for r in receipts):
            return receipts
        require(all(r.status == "RECORDED" and r.source_version == self._version for r in receipts),
                "REFERENCE_CONFLICT", "Cannot rebase pending intents onto a changed reference")
        require(len({r.hex_id for r in receipts}) == len(receipts), "RECEIPT_INVALID", "Conflicting updates for one cell")
        self._generation += 1
        self._version = f"{self._initial_version}:simulated-{self._generation}"
        confirmed = []
        for receipt in receipts:
            self._prices[receipt.hex_id] = receipt.price
            updated = replace(receipt, status="SIMULATED_EFFECTIVE", effective_reference_version=self._version)
            self._receipts[receipt.receipt_id] = updated
            self._audit.append(updated)
            confirmed.append(updated)
        return tuple(confirmed)
