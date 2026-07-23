from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field

from packages.common.logger import logger
from packages.positions.ledger import portfolio_ledger
from packages.positions.manager import position_manager


class ReconciliationIssue(BaseModel):
    issue_type: str
    severity: str
    description: str


class PositionReconciliationResult(BaseModel):
    is_reconciled: bool
    issues: List[ReconciliationIssue] = Field(default_factory=list)
    reconciled_at: datetime
    service_version: str = "1.0.0"


class PositionReconciliationService:
    """Reconciles portfolio ledger balances against position projections and cash reserves."""

    def reconcile_portfolio(self, current_time: Optional[datetime] = None) -> PositionReconciliationResult:
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        issues = []

        # 1. Negative Cash Balance Check
        if portfolio_ledger.cash_balance < Decimal("0.0"):
            issues.append(ReconciliationIssue(
                issue_type="NEGATIVE_CASH_BALANCE",
                severity="CRITICAL",
                description=f"Cash balance ({portfolio_ledger.cash_balance}) is negative."
            ))

        # 2. Available Cash Invariant
        if portfolio_ledger.available_cash > portfolio_ledger.cash_balance:
            issues.append(ReconciliationIssue(
                issue_type="AVAILABLE_CASH_EXCEEDS_TOTAL",
                severity="ERROR",
                description="Available cash exceeds total cash balance."
            ))

        # 3. Negative Asset Balances
        for asset, bal in portfolio_ledger.asset_balances.items():
            if bal < Decimal("0.0"):
                issues.append(ReconciliationIssue(
                    issue_type="NEGATIVE_ASSET_BALANCE",
                    severity="CRITICAL",
                    description=f"Ledger asset balance for {asset} ({bal}) is negative."
                ))

        # 4. Position & Ledger Consistency Checks
        for symbol, pos in position_manager.positions.items():
            base_asset = symbol.split("/")[0] if "/" in symbol else symbol
            ledger_asset_bal = portfolio_ledger.asset_balances.get(base_asset, Decimal("0.0"))

            # Check: CLOSED position residuals
            if pos.status == "CLOSED":
                if pos.quantity > Decimal("0.0"):
                    issues.append(ReconciliationIssue(
                        issue_type="CLOSED_POSITION_NON_ZERO_QTY",
                        severity="ERROR",
                        description=f"Closed position {symbol} has non-zero quantity ({pos.quantity})."
                    ))
                if pos.total_cost_basis > Decimal("0.0"):
                    issues.append(ReconciliationIssue(
                        issue_type="CLOSED_POSITION_NON_ZERO_COST",
                        severity="ERROR",
                        description=f"Closed position {symbol} has non-zero cost basis ({pos.total_cost_basis})."
                    ))
            else:
                # Check: OPEN position quantity vs ledger
                if pos.quantity != ledger_asset_bal:
                    issues.append(ReconciliationIssue(
                        issue_type="ASSET_QUANTITY_MISMATCH",
                        severity="ERROR",
                        description=f"Position qty for {symbol} ({pos.quantity}) != ledger ({ledger_asset_bal})."
                    ))

                # Check: Reservation invariant (avail + reserved == quantity)
                if pos.available_quantity + pos.reserved_exit_quantity != pos.quantity:
                    issues.append(ReconciliationIssue(
                        issue_type="RESERVATION_INVARIANT_MISMATCH",
                        severity="ERROR",
                        description=f"Position {symbol} avail ({pos.available_quantity}) + reserved != total."
                    ))

                # Check: Cost basis negative
                if pos.total_cost_basis < Decimal("0.0"):
                    issues.append(ReconciliationIssue(
                        issue_type="NEGATIVE_COST_BASIS",
                        severity="ERROR",
                        description=f"Position {symbol} cost basis ({pos.total_cost_basis}) is negative."
                    ))

        # 5. Peak Equity & Drawdown Invariants
        try:
            snapshot = position_manager.get_portfolio_snapshot(current_time)
            if snapshot.equity_peak < snapshot.nav:
                issues.append(ReconciliationIssue(
                    issue_type="EQUITY_PEAK_MISMATCH",
                    severity="ERROR",
                    description=f"Equity peak ({snapshot.equity_peak}) is lower than current NAV ({snapshot.nav})."
                ))

            if snapshot.drawdown_pct < Decimal("0.0") or snapshot.drawdown_pct > Decimal("1.0"):
                issues.append(ReconciliationIssue(
                    issue_type="INVALID_DRAWDOWN_RANGE",
                    severity="ERROR",
                    description=f"Drawdown percentage ({snapshot.drawdown_pct}) is outside [0, 1]."
                ))
        except Exception as exc:
            issues.append(ReconciliationIssue(
                issue_type="SNAPSHOT_GENERATION_FAILED",
                severity="CRITICAL",
                description=f"Failed to generate portfolio snapshot due to corrupted state: {exc}"
            ))

        is_clean = len(issues) == 0
        if not is_clean:
            logger.error("Portfolio reconciliation found mismatches", extra={"issue_count": len(issues)})

        return PositionReconciliationResult(
            is_reconciled=is_clean,
            issues=issues,
            reconciled_at=current_time,
            service_version="1.0.0"
        )


position_reconciliation_service = PositionReconciliationService()
