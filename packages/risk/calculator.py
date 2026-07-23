from decimal import ROUND_DOWN, Decimal
from typing import Optional

from pydantic import BaseModel


class PositionSizingResult(BaseModel):
    conservative_entry_price: Decimal
    raw_quantity: Decimal
    approved_quantity: Decimal
    approved_notional: Decimal
    actual_risk_amount: Decimal
    actual_risk_pct: Decimal
    is_valid: bool
    rejection_reason: Optional[str] = None


class PositionSizingCalculator:
    """Calculates position quantities in Decimal with strict round-down and risk caps."""

    def calculate_sizing(
        self,
        nav: Decimal,
        adjusted_risk_budget: Decimal,
        reference_price: Decimal,
        stop_price: Decimal,
        available_cash: Decimal,
        current_symbol_exposure: Decimal,
        current_gross_exposure: Decimal,
        max_symbol_allocation_pct: Decimal,
        max_total_exposure_pct: Decimal,
        entry_slippage_bps: Decimal = Decimal("10.0"),
        quantity_step_size: Decimal = Decimal("0.001"),
        minimum_quantity: Decimal = Decimal("0.001"),
        minimum_notional: Decimal = Decimal("10.00"),
        reserve_cash_pct: Decimal = Decimal("0.0500")
    ) -> PositionSizingResult:

        # 1. Conservative entry price
        conservative_entry_price = reference_price * (Decimal("1.0") + (entry_slippage_bps / Decimal("10000.0")))

        # 2. Stop distance
        stop_distance = conservative_entry_price - stop_price
        if stop_distance <= Decimal("0.0"):
            return PositionSizingResult(
                conservative_entry_price=conservative_entry_price,
                raw_quantity=Decimal("0.0"),
                approved_quantity=Decimal("0.0"),
                approved_notional=Decimal("0.0"),
                actual_risk_amount=Decimal("0.0"),
                actual_risk_pct=Decimal("0.0"),
                is_valid=False,
                rejection_reason="INVALID_STOP_DISTANCE_LE_ZERO"
            )

        # 3. Raw quantity from risk budget
        raw_quantity = adjusted_risk_budget / stop_distance

        # 4. Usable cash cap (with cash reserve)
        usable_cash = max(Decimal("0.0"), available_cash * (Decimal("1.0") - reserve_cash_pct))
        quantity_by_cash = usable_cash / conservative_entry_price

        # 5. Symbol cap
        max_symbol_notional = nav * max_symbol_allocation_pct
        remaining_symbol_notional = max(Decimal("0.0"), max_symbol_notional - current_symbol_exposure)
        quantity_by_symbol = remaining_symbol_notional / conservative_entry_price

        # 6. Total exposure cap
        max_total_notional = nav * max_total_exposure_pct
        remaining_total_notional = max(Decimal("0.0"), max_total_notional - current_gross_exposure)
        quantity_by_total = remaining_total_notional / conservative_entry_price

        # 7. Minimum pre-round quantity
        pre_round = min(raw_quantity, quantity_by_cash, quantity_by_symbol, quantity_by_total)

        if pre_round <= Decimal("0.0"):
            return PositionSizingResult(
                conservative_entry_price=conservative_entry_price,
                raw_quantity=raw_quantity,
                approved_quantity=Decimal("0.0"),
                approved_notional=Decimal("0.0"),
                actual_risk_amount=Decimal("0.0"),
                actual_risk_pct=Decimal("0.0"),
                is_valid=False,
                rejection_reason="EXPOSURE_OR_CASH_CAP_EXCEEDED"
            )

        # 8. Decimal Round Down to step size
        units = (pre_round / quantity_step_size).quantize(Decimal("1"), rounding=ROUND_DOWN)
        approved_quantity = units * quantity_step_size

        if approved_quantity < minimum_quantity:
            return PositionSizingResult(
                conservative_entry_price=conservative_entry_price,
                raw_quantity=raw_quantity,
                approved_quantity=Decimal("0.0"),
                approved_notional=Decimal("0.0"),
                actual_risk_amount=Decimal("0.0"),
                actual_risk_pct=Decimal("0.0"),
                is_valid=False,
                rejection_reason="QUANTITY_BELOW_MINIMUM"
            )

        # 9. Notional & Actual Risk Verification
        approved_notional = approved_quantity * conservative_entry_price
        if approved_notional < minimum_notional:
            return PositionSizingResult(
                conservative_entry_price=conservative_entry_price,
                raw_quantity=raw_quantity,
                approved_quantity=Decimal("0.0"),
                approved_notional=Decimal("0.0"),
                actual_risk_amount=Decimal("0.0"),
                actual_risk_pct=Decimal("0.0"),
                is_valid=False,
                rejection_reason="NOTIONAL_BELOW_MINIMUM"
            )

        actual_risk_amount = approved_quantity * stop_distance
        actual_risk_pct = actual_risk_amount / nav

        # Verify actual risk <= adjusted risk budget
        if actual_risk_amount > adjusted_risk_budget:
            return PositionSizingResult(
                conservative_entry_price=conservative_entry_price,
                raw_quantity=raw_quantity,
                approved_quantity=Decimal("0.0"),
                approved_notional=Decimal("0.0"),
                actual_risk_amount=Decimal("0.0"),
                actual_risk_pct=Decimal("0.0"),
                is_valid=False,
                rejection_reason="ACTUAL_RISK_EXCEEDS_BUDGET"
            )

        return PositionSizingResult(
            conservative_entry_price=conservative_entry_price,
            raw_quantity=raw_quantity,
            approved_quantity=approved_quantity,
            approved_notional=approved_notional,
            actual_risk_amount=actual_risk_amount,
            actual_risk_pct=actual_risk_pct,
            is_valid=True
        )


position_sizing_calculator = PositionSizingCalculator()
