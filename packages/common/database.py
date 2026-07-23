from typing import Any, Dict

from packages.common.config import settings
from packages.common.logger import logger


async def check_postgres_health() -> Dict[str, Any]:
    """Dynamically checks PostgreSQL database connectivity."""
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        url = settings.DATABASE_URL
        if "+asyncpg" not in url and "postgresql" in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://")

        engine = create_async_engine(
            url,
            echo=False,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=0
        )
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            val = result.scalar()
            if val == 1:
                await engine.dispose()
                return {"status": "online", "message": "PostgreSQL database reachable"}
        await engine.dispose()
    except Exception as e:
        logger.warning("PostgreSQL health check failed", extra={"error": str(e)})
        return {"status": "offline", "error": str(e)}
    return {"status": "offline", "error": "Unknown database query failure"}
