"""F-04 recovery reconciliation LOGIC (pure, no DB)."""

from decimal import Decimal

from packages.persistence.reconciliation import reconcile_session


def _buy_ledger(fill_id: str):
    # BUY 0.1 BTC @ 50000: cash debit 5000, fee 5, asset credit 0.1
    return [
        {"entry_id": f"{fill_id}-c", "fill_id": fill_id, "asset": "USDT", "entry_type": "CASH_DEBIT", "amount": "5000"},
        {"entry_id": f"{fill_id}-f", "fill_id": fill_id, "asset": "USDT", "entry_type": "FEE_DEBIT", "amount": "5"},
        {"entry_id": f"{fill_id}-a", "fill_id": fill_id, "asset": "BTC", "entry_type": "ASSET_CREDIT", "amount": "0.1"},
    ]


def test_clean_state_reconciles() -> None:
    fid = "F1"
    res = reconcile_session(
        initial_cash=Decimal("10000"),
        ledger_rows=_buy_ledger(fid),
        fill_rows=[{"fill_id": fid}],
        materialized_cash=Decimal("4995"),
        materialized_positions={"BTC": Decimal("0.1")},
    )
    assert res.passed is True
    assert res.recovery_status == "READY"


def test_cash_imbalance_detected() -> None:
    fid = "F1"
    res = reconcile_session(
        initial_cash=Decimal("10000"),
        ledger_rows=_buy_ledger(fid),
        fill_rows=[{"fill_id": fid}],
        materialized_cash=Decimal("5000"),  # wrong (should be 4995)
        materialized_positions={"BTC": Decimal("0.1")},
    )
    assert res.passed is False
    assert any("CASH_IMBALANCE" in i for i in res.issues)
    assert res.recovery_status == "RECOVERY_REQUIRED"


def test_unlinked_ledger_entry_detected() -> None:
    res = reconcile_session(
        initial_cash=Decimal("10000"),
        ledger_rows=_buy_ledger("GHOST"),   # references a fill that is not persisted
        fill_rows=[],
        materialized_cash=Decimal("4995"),
        materialized_positions={"BTC": Decimal("0.1")},
    )
    assert res.passed is False
    assert any("UNLINKED_LEDGER_ENTRY" in i for i in res.issues)


def test_position_mismatch_detected() -> None:
    fid = "F1"
    res = reconcile_session(
        initial_cash=Decimal("10000"),
        ledger_rows=_buy_ledger(fid),
        fill_rows=[{"fill_id": fid}],
        materialized_cash=Decimal("4995"),
        materialized_positions={"BTC": Decimal("0.2")},  # wrong (ledger implies 0.1)
    )
    assert res.passed is False
    assert any("POSITION_MISMATCH" in i for i in res.issues)


def test_negative_cash_detected() -> None:
    fid = "F1"
    over = [{"entry_id": "x", "fill_id": fid, "asset": "USDT", "entry_type": "CASH_DEBIT", "amount": "20000"}]
    res = reconcile_session(
        initial_cash=Decimal("10000"),
        ledger_rows=over,
        fill_rows=[{"fill_id": fid}],
        materialized_cash=Decimal("-10000"),
        materialized_positions={},
    )
    assert res.passed is False
    assert any("NEGATIVE_CASH" in i for i in res.issues)
