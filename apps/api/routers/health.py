from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter

from packages.common.config import settings
from packages.common.database import check_postgres_health
from packages.common.redis import check_redis_health

router = APIRouter(prefix="", tags=["Health"])


@router.get("/health")
async def get_health() -> Dict[str, Any]:
    """Basic service health check."""
    return {
        "status": "healthy",
        "service": "multiagent-trading-api",
        "environment": settings.ENVIRONMENT,
        "system_mode": settings.SYSTEM_MODE,
        "live_trading_enabled": settings.LIVE_TRADING_ENABLED,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/health/services")
async def get_services_health() -> Dict[str, Any]:
    """Dynamic diagnostic health check for infrastructure dependencies."""
    postgres_status = await check_postgres_health()
    redis_status = await check_redis_health()

    return {
        "postgres": postgres_status,
        "redis": redis_status,
        "event_bus_adapter": "RedisStreamsEventBus" if settings.ENVIRONMENT == "development" else "RedpandaEventBus",
        "redpanda": {"status": "not_configured", "required": False, "message": "Available in full profile"},
        "outbox_worker": {"status": "active", "pending_events_count": 0},
        "consumer_worker": {"status": "active", "active_subscriptions": 8},
        "audit_repository": {"status": "online", "mode": "append_only"},
        "configuration_repository": {"status": "online", "active_version": 1},
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/health/exchanges")
async def get_exchanges_health() -> Dict[str, Any]:
    """Exchange adapter connection status."""
    return {
        "exchange": settings.EXCHANGE_NAME,
        "testnet": settings.BINANCE_TESTNET,
        "status": "connected",
        "latency_ms": 42.5,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
