from typing import Any, Dict

from packages.common.config import settings
from packages.common.logger import logger


async def check_redis_health() -> Dict[str, Any]:
    """Dynamically checks Redis connection by setting/getting a health check key with TTL."""
    try:
        import redis.asyncio as redis
        r = redis.from_url(settings.REDIS_URL, socket_timeout=2.0)
        async with r:
            pong = await r.ping()
            if pong:
                await r.set("health_check_key", "ok", ex=10)
                val = await r.get("health_check_key")
                if val == b"ok" or val == "ok":
                    msg = "Redis reachable and key set/get verified"
                    return {"status": "online", "message": msg}
    except Exception as e:
        logger.warning("Redis health check failed", extra={"error": str(e)})
        return {"status": "offline", "error": str(e)}
    return {"status": "offline", "error": "Unknown Redis connection failure"}
