from packages.agents.breakout import BreakoutAgent
from packages.agents.models import AgentSignal
from packages.agents.regime import MarketRegimeAgent
from packages.agents.reversion import MeanReversionAgent
from packages.agents.trend import TrendAgent


def test_strategy_agents_contain_no_trading_methods_or_clients():
    """Safety Test: Proves strategy agents contain NO trading methods."""
    prohibited_substrings = [
        "create_order", "place_order", "cancel_order", "execute_trade",
        "buy", "sell", "execution_engine", "exchange_client"
    ]

    for agent_cls in [MarketRegimeAgent, TrendAgent, MeanReversionAgent, BreakoutAgent]:
        method_names = [m for m in dir(agent_cls) if not m.startswith("__")]
        for m in method_names:
            for prohibited in prohibited_substrings:
                assert prohibited not in m.lower(), (
                    f"Safety Violation: Agent class '{agent_cls.__name__}' contains prohibited trading method '{m}'"
                )


def test_agent_signal_schema_strictly_prohibits_execution_fields():
    """Safety Test: Proves AgentSignal schema contains NO quantity, notional, or leverage execution fields."""
    signal_fields = list(AgentSignal.model_fields.keys())
    prohibited_fields = ["quantity", "notional", "leverage", "approved_risk", "order_type", "client_order_id"]

    for pf in prohibited_fields:
        assert pf not in signal_fields, (
            f"Safety Violation: AgentSignal schema contains forbidden execution field '{pf}'"
        )
