"""Phase 8: stable error schema + request-ID propagation.

Covers `PortError` (typed service-layer failures), request validation failures, and any
otherwise-unhandled exception - a caller never sees a raw traceback, an internal file path, or
a driver-specific exception message for those. `HTTPException` (403/404 raised directly by a
route, e.g. recommendations.py's "unknown proposal"/"unknown registry") is deliberately left to
FastAPI's own default handler and its standard `{"detail": ...}` body - 26 pre-existing routers
across this app already raise `HTTPException` and rely on that exact shape, and this task's
storage/behavior-preservation rule (Section 4, rule 20) means Phase 8 must not silently change
their response contract app-wide.
"""

import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from packages.common.logger import logger
from packages.ports.errors import PortError

REQUEST_ID_HEADER = "X-Request-ID"


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    request_id: str
    reason_codes: List[str] = []
    details: Optional[Dict[str, Any]] = None


def get_or_create_request_id(request: Request) -> str:
    return request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(PortError)
    async def _port_error_handler(request: Request, exc: PortError) -> JSONResponse:
        request_id = get_or_create_request_id(request)
        logger.warning(
            "Port error handled at API boundary",
            extra={"request_id": request_id, "reason_code": exc.reason_code, "path": request.url.path},
        )
        body = ErrorResponse(
            error_code=exc.reason_code, message=str(exc), request_id=request_id, reason_codes=[exc.reason_code],
        )
        return JSONResponse(status_code=502, content=body.model_dump(), headers={REQUEST_ID_HEADER: request_id})

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = get_or_create_request_id(request)
        body = ErrorResponse(
            error_code="INVALID_REQUEST", message="Request validation failed.", request_id=request_id,
            reason_codes=["REQUEST_VALIDATION_FAILED"],
        )
        return JSONResponse(status_code=422, content=body.model_dump(), headers={REQUEST_ID_HEADER: request_id})

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = get_or_create_request_id(request)
        # Never surface str(exc) here - it can contain internal paths or connection strings.
        # The full exception is only in the server-side log, keyed by request_id.
        logger.error(
            "Unhandled exception at API boundary",
            extra={"request_id": request_id, "path": request.url.path, "exception_type": type(exc).__name__},
        )
        body = ErrorResponse(
            error_code="INTERNAL_ERROR", message="An unexpected error occurred.", request_id=request_id,
            reason_codes=["UNEXPECTED_ERROR"],
        )
        return JSONResponse(status_code=500, content=body.model_dump(), headers={REQUEST_ID_HEADER: request_id})
