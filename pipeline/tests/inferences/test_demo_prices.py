"""G08.2: explicit in-memory TEST_ONLY receipt protocol, not production DB tests."""
from __future__ import annotations
from decimal import Decimal
import pytest
from surge_ml.errors import GGSOError
from surge_ml.datasets.fixtures import make_fixture
from surge_ml.integrations.demo_prices import DemoPriceBook, ManualPolicy


@pytest.fixture
def book():
    fixture = make_fixture()
    policy = ManualPolicy(usage="TEST_ONLY", version="test-manual-policy-v1", surge_min="1.0", surge_max="2.0",
                          max_deviation="0.4", step="0.01", precision=2)
    return DemoPriceBook(fixture.operational, policy)


def record(book, **changes):
    args = dict(operator_id="test-operator", role="OPERATOR", hex_id="test-hex-00", price="1.23",
                expected_reference_version="test-effective-price-v1", idempotency_key="test-key-01", reason="TEST_ONLY manual edit")
    args.update(changes)
    return book.record(**args)


def test_pending_record_does_not_change_effective_reference(book):
    before = book.reference()
    receipt = record(book)
    assert receipt.status == "RECORDED"
    assert book.reference() == before
    assert receipt.production_effective is False
    assert book.audit == (receipt,)


def test_confirm_selected_subset_changes_only_selected_reference(book):
    first = record(book)
    second = record(book, hex_id="test-hex-01", price="1.4", idempotency_key="test-key-02")
    confirmed = book.confirm_simulated_effective((first.receipt_id,))
    version, prices = book.reference()
    assert prices == {"test-hex-00": Decimal("1.23"), "test-hex-01": Decimal("1.2")}
    assert version != "test-effective-price-v1"
    assert confirmed[0].status == "SIMULATED_EFFECTIVE"
    assert confirmed[0].production_effective is False
    assert second.status == "RECORDED"
    assert len(book.audit) == 3
    assert book.confirm_simulated_effective((first.receipt_id,)) == confirmed
    assert len(book.audit) == 3
    with pytest.raises(GGSOError, match="rebase"):
        book.confirm_simulated_effective((second.receipt_id,))


def test_atomic_multi_receipt_simulated_confirmation(book):
    first = record(book)
    second = record(book, hex_id="test-hex-01", price="1.4", idempotency_key="test-key-02")
    receipts = book.confirm_simulated_effective((first.receipt_id, second.receipt_id))
    assert {r.effective_reference_version for r in receipts} == {book.reference()[0]}
    assert book.reference()[1]["test-hex-01"] == Decimal("1.4")


def test_idempotency_preserves_receipt_and_rejects_conflicting_intent(book):
    receipt = record(book)
    assert record(book) == receipt
    assert len(book.audit) == 1
    with pytest.raises(GGSOError, match="different intent"):
        record(book, price="1.24")
    book.confirm_simulated_effective((receipt.receipt_id,))
    assert record(book).status == "SIMULATED_EFFECTIVE"
    with pytest.raises(GGSOError, match="Stale"):
        record(book, idempotency_key="new-key")


@pytest.mark.parametrize("changes", [{"role": "VIEWER"}, {"reason": ""}, {"hex_id": "unknown"},
    {"price": "1.001"}, {"price": "1.61"}, {"price": "0.9"}, {"price": "NaN"}, {"price": 1.23}])
def test_permission_bounds_precision_and_missing_values_fail_without_side_effects(book, changes):
    before = book.reference()
    with pytest.raises(ValueError):
        record(book, **changes)
    assert book.reference() == before
    assert not book.audit


def test_no_implicit_forecast_optimizer_or_publication_in_receipt_protocol(book, monkeypatch):
    import surge_ml.inferences.service as runner
    def forbidden(*args, **kwargs):
        raise AssertionError("Operator receipt unexpectedly invoked GGSO")
    monkeypatch.setattr(runner, "run_decision", forbidden)
    receipt = record(book)
    book.confirm_simulated_effective((receipt.receipt_id,))
    assert book.reference()[1]["test-hex-00"] == Decimal("1.23")
