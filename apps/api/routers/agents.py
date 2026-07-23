from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="", tags=["Agents & Strategies"])

agents_registry = [
    {
        "agent_id": "regime_agent_v1",
        "name": "Market Regime Agent",
        "type": "CONTEXT",
        "enabled": True,
        "weight": 1.0,
        "description": "Classifies market into Trend, Sideways, Volatility or Crisis regimes"
    },
    {
        "agent_id": "trend_agent_v1",
        "name": "Multi-Timeframe Trend Agent",
        "type": "ALPHA",
        "enabled": True,
        "weight": 0.35,
        "description": "Captures trend momentum across 15m, 1h, and 4h timeframes"
    },
    {
        "agent_id": "mean_reversion_v1",
        "name": "VWAP Mean Reversion Agent",
        "type": "ALPHA",
        "enabled": True,
        "weight": 0.35,
        "description": "Identifies statistical overbought/oversold extremes during sideways regimes"
    },
    {
        "agent_id": "breakout_agent_v1",
        "name": "Volatility Compression Breakout Agent",
        "type": "ALPHA",
        "enabled": True,
        "weight": 0.30,
        "description": "Detects high-volume volatility compression expansion breakouts"
    },
    {
        "agent_id": "critic_agent_v1",
        "name": "Critic & Scrutiny Agent",
        "type": "GOVERNANCE",
        "enabled": True,
        "weight": 1.0,
        "description": "Finds reasons NOT to trade and checks for signal conflicts"
    }
]


@router.get("/agents")
async def list_agents() -> List[Dict[str, Any]]:
    return agents_registry


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str) -> Dict[str, Any]:
    for agent in agents_registry:
        if agent["agent_id"] == agent_id:
            return agent
    raise HTTPException(status_code=404, detail="Agent not found")


@router.post("/agents/{agent_id}/enable")
async def enable_agent(agent_id: str) -> Dict[str, Any]:
    for agent in agents_registry:
        if agent["agent_id"] == agent_id:
            agent["enabled"] = True
            return {"message": f"Agent {agent_id} enabled", "agent": agent}
    raise HTTPException(status_code=404, detail="Agent not found")


@router.post("/agents/{agent_id}/disable")
async def disable_agent(agent_id: str) -> Dict[str, Any]:
    for agent in agents_registry:
        if agent["agent_id"] == agent_id:
            agent["enabled"] = False
            return {"message": f"Agent {agent_id} disabled", "agent": agent}
    raise HTTPException(status_code=404, detail="Agent not found")


@router.get("/signals")
async def get_latest_signals() -> List[Dict[str, Any]]:
    return []


@router.get("/strategies")
async def list_strategies() -> List[Dict[str, Any]]:
    return [
        {"strategy_id": "trend_momentum_v1", "name": "Trend Momentum", "active": True},
        {"strategy_id": "mean_reversion_vwap_v1", "name": "VWAP Mean Reversion", "active": True},
        {"strategy_id": "range_breakout_v1", "name": "Range Breakout", "active": True}
    ]


@router.get("/strategies/{strategy_id}/performance")
async def get_strategy_performance(strategy_id: str) -> Dict[str, Any]:
    return {
        "strategy_id": strategy_id,
        "sharpe_ratio": 1.85,
        "sortino_ratio": 2.40,
        "win_rate": 0.58,
        "profit_factor": 1.72,
        "total_trades": 142
    }
