from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.error_schema import REQUEST_ID_HEADER, get_or_create_request_id, register_error_handlers
from apps.api.routers import (
    agents,
    agents_m4,
    audit,
    backtest,
    backtests,
    campaign,
    chat,
    configurations,
    data_quality,
    events,
    execution,
    features,
    governance,
    health,
    incidents,
    market_data,
    operations,
    paper,
    portfolio,
    positions,
    recommendations,
    risk,
    risk_m6,
    security,
    trading,
)
from packages.common.config import settings
from packages.common.logger import logger
from packages.telemetry.metrics import metrics_registry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Mandatory fail-closed security assertions on startup
    if settings.LIVE_TRADING_ENABLED:
        raise RuntimeError("SECURITY_KILL_SWITCH: LIVE_TRADING_ENABLED is True! Execution halted immediately.")
    if settings.PRIVATE_EXCHANGE_API_ENABLED:
        raise RuntimeError("SECURITY_KILL_SWITCH: PRIVATE_EXCHANGE_API_ENABLED is True! Execution halted immediately.")

    logger.info(
        "Starting Multi-Agent Trading System API Server",
        extra={
            "environment": settings.ENVIRONMENT,
            "mode": settings.SYSTEM_MODE,
            "live_enabled": settings.LIVE_TRADING_ENABLED,
        },
    )
    yield
    logger.info("Shutting down Multi-Agent Trading System API Server")


app = FastAPI(
    title="Multi-Agent Cryptocurrency Trading System API",
    description="Production-Grade 3-Tier Multi-Agent Trading Backend API",
    version="0.3.0",
    lifespan=lifespan,
)

# Enable CORS for Frontend React Dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Request-ID"],
)

# Register Routers
app.include_router(health.router)
app.include_router(trading.router)
app.include_router(portfolio.router)
app.include_router(agents.router)
app.include_router(risk.router)
app.include_router(backtest.router)
app.include_router(incidents.router)
app.include_router(events.router)
app.include_router(audit.router)
app.include_router(configurations.router)
app.include_router(market_data.router)
app.include_router(data_quality.router)
app.include_router(features.router)
app.include_router(agents_m4.router)
app.include_router(governance.router)
app.include_router(risk_m6.router)
app.include_router(execution.router)
app.include_router(positions.router)
app.include_router(backtests.router)
app.include_router(paper.router)
app.include_router(operations.router)
app.include_router(security.router)
app.include_router(recommendations.router)
app.include_router(chat.router)
app.include_router(campaign.router)

register_error_handlers(app)


@app.exception_handler(campaign.CampaignAPIError)
async def campaign_error_handler(
    request: Request,
    exc: campaign.CampaignAPIError,
) -> JSONResponse:
    request_id = get_or_create_request_id(request)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error_code": exc.code,
            "message": exc.message,
            "request_id": request_id,
            "reason_codes": [exc.code],
            "details": None,
        },
        headers={REQUEST_ID_HEADER: request_id},
    )


@app.get("/metrics")
async def prometheus_metrics():
    return Response(content=metrics_registry.export_prometheus_text(), media_type="text/plain")


@app.get("/")
async def root():
    return {
        "system": "Multi-Agent Cryptocurrency Trading Platform",
        "docs_url": "/docs",
        "health_check": "/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("apps.api.main:app", host=settings.API_HOST, port=settings.API_PORT, reload=True)
