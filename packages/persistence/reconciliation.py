"""Pure recovery reconciliation logic (F-04).

Derives cash / asset quantities from the durable ledger + fill rows and compares them against
the materialized session state. These functions are pure (operate on plain rows), so they are
unit-testable without a database. They decide whether a recovering session may become READY or
must stay RECOVERY_REQUIRED. Running this against real PostgreSQL rows is NOT verified here.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Iterable, List, Mapping

# Ledger entry types (must match packages/positions/ledger.py).
CASH_CREDIT = "CASH_CREDIT"
CASH_DEBIT = "CASH_DEBIT"
FEE_DEBIT = "FEE_DEBIT"
ASSET_CREDIT = "ASSET_CREDIT"
ASSET_DEBIT = "ASSET_DEBIT"


@dataclass
class ReconciliationResult:
    passed: bool
    issues: List[str] = field(default_factory=list)

    @property
    def recovery_status(self) -> str:
        return "READY" if self.passed else "RECOVERY_REQUIRED"


def derive_cash(initial_cash: Decimal, ledger_rows: Iterable[Mapping]) -> Decimal:
    cash = initial_cash
    for e in ledger_rows:
        etype, amount = e["entry_type"], Decimal(str(e["amount"]))
        if etype == CASH_CREDIT:
            cash += amount
        elif etype in (CASH_DEBIT, FEE_DEBIT):
            cash -= amount
    return cash


def derive_asset_quantities(ledger_rows: Iterable[Mapping]) -> Dict[str, Decimal]:
    qty: Dict[str, Decimal] = {}
    for e in ledger_rows:
        etype = e["entry_type"]
        if etype in (ASSET_CREDIT, ASSET_DEBIT):
            asset = e["asset"]
            amount = Decimal(str(e["amount"]))
            cur = qty.get(asset, Decimal("0"))
            qty[asset] = cur + amount if etype == ASSET_CREDIT else cur - amount
    return qty


def reconcile_session(
    *,
    initial_cash: Decimal,
    ledger_rows: List[Mapping],
    fill_rows: List[Mapping],
    materialized_cash: Decimal,
    materialized_positions: Mapping[str, Decimal],
) -> ReconciliationResult:
    """Compare durable-ledger-derived state against materialized state; enumerate mismatches."""
    issues: List[str] = []

    fill_ids = {str(f["fill_id"]) for f in fill_rows}

    # 1. Every ledger entry must reference a persisted fill (no unlinked ledger rows).
    for e in ledger_rows:
        if str(e["fill_id"]) not in fill_ids:
            issues.append(f"UNLINKED_LEDGER_ENTRY:{e.get('entry_id', '?')}")

    # 2. Cash derived from the ledger must equal the materialized cash.
    derived_cash = derive_cash(initial_cash, ledger_rows)
    if derived_cash != materialized_cash:
        issues.append(f"CASH_IMBALANCE derived={derived_cash} materialized={materialized_cash}")

    # 3. Asset quantities derived from the ledger must equal materialized position quantities.
    derived_qty = derive_asset_quantities(ledger_rows)
    for asset, dqty in derived_qty.items():
        mqty = Decimal(str(materialized_positions.get(asset, Decimal("0"))))
        if dqty != mqty:
            issues.append(f"POSITION_MISMATCH:{asset} derived={dqty} materialized={mqty}")

    # 4. No negative cash / negative position may survive recovery.
    if derived_cash < Decimal("0"):
        issues.append(f"NEGATIVE_CASH:{derived_cash}")
    for asset, dqty in derived_qty.items():
        if dqty < Decimal("0"):
            issues.append(f"NEGATIVE_POSITION:{asset}:{dqty}")

    return ReconciliationResult(passed=len(issues) == 0, issues=issues)
