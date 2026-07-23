from datetime import datetime
from decimal import Decimal
from typing import List, Tuple

from packages.common.logger import logger
from packages.risk.models import PortfolioRiskSnapshot, RiskState
from packages.risk.policy import RiskPolicyConfig


class RiskStateMachine:
    """Manages global Risk State transitions and Kill Switch activation."""

    def __init__(self, initial_state: RiskState = RiskState.NORMAL) -> None:
        self.state = initial_state

    def evaluate_state(
        self,
        snapshot: PortfolioRiskSnapshot,
        policy: RiskPolicyConfig,
        current_time: datetime
    ) -> Tuple[RiskState, List[str], bool]:
        reasons = []
        kill_triggered = False

        # Calculate daily and weekly loss percentages
        daily_loss_pct = Decimal("0.0")
        if snapshot.nav > Decimal("0"):
            daily_loss_pct = max(Decimal("0.0"), -snapshot.realized_pnl_today / snapshot.nav)

        weekly_loss_pct = Decimal("0.0")
        if snapshot.nav > Decimal("0"):
            weekly_loss_pct = max(Decimal("0.0"), -snapshot.realized_pnl_week / snapshot.nav)

        # 1. Hard Stop / Kill Switch Check
        if daily_loss_pct >= policy.max_daily_loss_pct:
            reasons.append(f"DAILY_LOSS_HARD_LIMIT_BREACHED ({daily_loss_pct * 100:.2f}%)")
            kill_triggered = True

        if weekly_loss_pct >= policy.max_weekly_loss_pct:
            reasons.append(f"WEEKLY_LOSS_HARD_LIMIT_BREACHED ({weekly_loss_pct * 100:.2f}%)")
            kill_triggered = True

        if snapshot.current_drawdown_pct >= policy.hard_stop_drawdown_pct:
            reasons.append(f"HARD_STOP_DRAWDOWN_BREACHED ({snapshot.current_drawdown_pct * 100:.2f}%)")
            kill_triggered = True

        if kill_triggered:
            self.state = RiskState.HARD_STOP
            logger.error("KILL SWITCH ACTIVATED", extra={"reasons": reasons, "account_id": snapshot.account_id})
            return RiskState.HARD_STOP, reasons, True

        # 2. Soft Stop Check
        if snapshot.current_drawdown_pct >= policy.soft_stop_drawdown_pct:
            reasons.append(f"SOFT_STOP_DRAWDOWN_BREACHED ({snapshot.current_drawdown_pct * 100:.2f}%)")
            self.state = RiskState.SOFT_STOP
            return RiskState.SOFT_STOP, reasons, False

        # 3. Warning Check
        is_warn_daily = daily_loss_pct >= policy.daily_loss_warning_pct
        is_warn_dd = snapshot.current_drawdown_pct >= policy.warning_drawdown_pct
        if is_warn_daily or is_warn_dd:
            reasons.append("RISK_WARNING_THRESHOLD_REACHED")
            self.state = RiskState.WARNING
            return RiskState.WARNING, reasons, False

        # 4. Normal
        self.state = RiskState.NORMAL
        return RiskState.NORMAL, reasons, False

    def manual_halt(self, operator_id: str) -> Tuple[RiskState, List[str]]:
        self.state = RiskState.MANUAL_HALT
        reasons = [f"MANUAL_HALT_TRIGGERED_BY_{operator_id}"]
        logger.warning("Manual Risk Halt Triggered", extra={"operator_id": operator_id})
        return RiskState.MANUAL_HALT, reasons


risk_state_machine = RiskStateMachine()
