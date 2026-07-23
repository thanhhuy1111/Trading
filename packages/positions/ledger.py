from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from packages.common.logger import logger
from packages.execution.models import Fill
from packages.positions.models import LedgerEntry, LedgerEntryType, RealizedPnlEntry


class PortfolioLedger:
    """Append-Only Portfolio Ledger enforcing strict accounting rules."""

    def __init__(self, initial_cash: Decimal = Decimal("100000.00"), account_id: str = "SIM_ACCOUNT_001") -> None:
        self.account_id = account_id
        self.cash_balance = initial_cash
        self.available_cash = initial_cash
        self.asset_balances: Dict[str, Decimal] = {}
        self.ledger_entries: List[LedgerEntry] = []
        self.processed_fill_ids: Dict[UUID, bool] = {}
        self.sequence_counter = 0

    def reset(self, initial_cash: Decimal = Decimal("100000.00")) -> None:
        """Reset ledger state for fresh testing or replay."""
        self.cash_balance = initial_cash
        self.available_cash = initial_cash
        self.asset_balances.clear()
        self.ledger_entries.clear()
        self.processed_fill_ids.clear()
        self.sequence_counter = 0

    def process_fill(
        self,
        fill: Fill,
        current_time: Optional[datetime] = None,
        average_entry_price: Decimal = Decimal("0.0")
    ) -> Tuple[List[LedgerEntry], Optional[RealizedPnlEntry]]:

        if current_time is None:
            current_time = datetime.now(timezone.utc)

        # 1. Fill Idempotency Check
        if fill.fill_id in self.processed_fill_ids:
            logger.info("Fill already processed by PortfolioLedger", extra={"fill_id": str(fill.fill_id)})
            return [], None

        self.processed_fill_ids[fill.fill_id] = True
        tx_id = uuid4()
        new_entries: List[LedgerEntry] = []
        pnl_entry: Optional[RealizedPnlEntry] = None

        if fill.side == "BUY":
            # BUY Accounting: CASH_DEBIT for quote quantity, FEE_DEBIT for fee, ASSET_CREDIT for quantity
            total_cash_debit = fill.quote_quantity + fill.fee
            if total_cash_debit > self.cash_balance:
                logger.error(
                    "Insufficient cash for BUY fill",
                    extra={"required": str(total_cash_debit), "available": str(self.cash_balance)}
                )
                raise ValueError("INSUFFICIENT_CASH: Fill processing rejected to prevent negative cash balance")

            self.cash_balance -= total_cash_debit
            self.available_cash -= total_cash_debit

            base_asset = fill.symbol.split("/")[0] if "/" in fill.symbol else fill.symbol
            curr_asset_bal = self.asset_balances.get(base_asset, Decimal("0.0"))
            self.asset_balances[base_asset] = curr_asset_bal + fill.quantity

            # 1. CASH_DEBIT entry (quote quantity)
            self.sequence_counter += 1
            e1 = LedgerEntry(
                transaction_id=tx_id,
                account_id=self.account_id,
                asset="USDT",
                entry_type=LedgerEntryType.CASH_DEBIT,
                amount=fill.quote_quantity,
                fill_id=fill.fill_id,
                reference_type="BUY_FILL_CASH",
                reference_id=fill.exchange_fill_id,
                effective_at=fill.executed_at,
                recorded_at=current_time,
                sequence_number=self.sequence_counter
            )
            new_entries.append(e1)

            # 2. FEE_DEBIT entry (fee amount)
            if fill.fee > Decimal("0.0"):
                self.sequence_counter += 1
                e_fee = LedgerEntry(
                    transaction_id=tx_id,
                    account_id=self.account_id,
                    asset=fill.fee_asset or "USDT",
                    entry_type=LedgerEntryType.FEE_DEBIT,
                    amount=fill.fee,
                    fill_id=fill.fill_id,
                    reference_type="BUY_FILL_FEE",
                    reference_id=fill.exchange_fill_id,
                    effective_at=fill.executed_at,
                    recorded_at=current_time,
                    sequence_number=self.sequence_counter
                )
                new_entries.append(e_fee)

            # 3. ASSET_CREDIT entry (base asset quantity)
            self.sequence_counter += 1
            e2 = LedgerEntry(
                transaction_id=tx_id,
                account_id=self.account_id,
                asset=base_asset,
                entry_type=LedgerEntryType.ASSET_CREDIT,
                amount=fill.quantity,
                fill_id=fill.fill_id,
                reference_type="BUY_FILL_ASSET",
                reference_id=fill.exchange_fill_id,
                effective_at=fill.executed_at,
                recorded_at=current_time,
                sequence_number=self.sequence_counter
            )
            new_entries.append(e2)

        elif fill.side == "SELL":
            # SELL Accounting: CASH_CREDIT for gross quote quantity, FEE_DEBIT for fee, ASSET_DEBIT for asset
            base_asset = fill.symbol.split("/")[0] if "/" in fill.symbol else fill.symbol
            curr_asset_bal = self.asset_balances.get(base_asset, Decimal("0.0"))
            if fill.quantity > curr_asset_bal:
                logger.error(
                    "Insufficient asset for SELL fill",
                    extra={"required": str(fill.quantity), "available": str(curr_asset_bal)}
                )
                raise ValueError("INSUFFICIENT_ASSET: Fill rejected to prevent negative asset balance")

            net_proceeds = fill.quote_quantity - fill.fee
            self.cash_balance += net_proceeds
            self.available_cash += net_proceeds
            self.asset_balances[base_asset] = curr_asset_bal - fill.quantity

            released_cost = fill.quantity * average_entry_price
            realized_pnl = net_proceeds - released_cost

            # 1. CASH_CREDIT entry (gross quote quantity)
            self.sequence_counter += 1
            e1 = LedgerEntry(
                transaction_id=tx_id,
                account_id=self.account_id,
                asset="USDT",
                entry_type=LedgerEntryType.CASH_CREDIT,
                amount=fill.quote_quantity,
                fill_id=fill.fill_id,
                reference_type="SELL_FILL_CASH",
                reference_id=fill.exchange_fill_id,
                effective_at=fill.executed_at,
                recorded_at=current_time,
                sequence_number=self.sequence_counter
            )
            new_entries.append(e1)

            # 2. FEE_DEBIT entry (fee amount)
            if fill.fee > Decimal("0.0"):
                self.sequence_counter += 1
                e_fee = LedgerEntry(
                    transaction_id=tx_id,
                    account_id=self.account_id,
                    asset=fill.fee_asset or "USDT",
                    entry_type=LedgerEntryType.FEE_DEBIT,
                    amount=fill.fee,
                    fill_id=fill.fill_id,
                    reference_type="SELL_FILL_FEE",
                    reference_id=fill.exchange_fill_id,
                    effective_at=fill.executed_at,
                    recorded_at=current_time,
                    sequence_number=self.sequence_counter
                )
                new_entries.append(e_fee)

            # 3. ASSET_DEBIT entry (base asset quantity)
            self.sequence_counter += 1
            e2 = LedgerEntry(
                transaction_id=tx_id,
                account_id=self.account_id,
                asset=base_asset,
                entry_type=LedgerEntryType.ASSET_DEBIT,
                amount=fill.quantity,
                fill_id=fill.fill_id,
                reference_type="SELL_FILL_ASSET",
                reference_id=fill.exchange_fill_id,
                effective_at=fill.executed_at,
                recorded_at=current_time,
                sequence_number=self.sequence_counter
            )
            new_entries.append(e2)

            pnl_entry = RealizedPnlEntry(
                account_id=self.account_id,
                position_id=uuid4(),
                sell_fill_id=fill.fill_id,
                quantity=fill.quantity,
                sale_proceeds=fill.quote_quantity,
                released_cost_basis=released_cost,
                exit_fee=fill.fee,
                realized_pnl=realized_pnl,
                realized_at=fill.executed_at
            )

        self.ledger_entries.extend(new_entries)
        return new_entries, pnl_entry


portfolio_ledger = PortfolioLedger()
